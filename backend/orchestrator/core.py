"""Orchestrator 主体 —— 只做四件事：路由、分发、传数据、兜底。

三层降级兜底：
  第一层 自动重试（with_retry，指数退避）
  第二层 Agent 级降级（各 Agent 自己的 fallback 逻辑）
  第三层 系统级兜底（handle 的 try/except，永远返回有效 AgentResponse）
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

from ..infra.llm_factory import llm_factory
from ..infra.retry import with_retry
from ..observability.logger import log_event
from ..observability.trace import finish_trace, span, start_trace
from .pipeline import CONTEXT_MAPPING, PIPELINE_GATES, PIPELINES, GateResult
from .registry import graph_registry
from .router import IntentRouter, SessionRegistry
from .schema import AGENT_META, AgentRequest, AgentResponse, AgentType, RouteResult


class Orchestrator:
    def __init__(self) -> None:
        self.sessions = SessionRegistry()
        self.router = IntentRouter(self.sessions)
        self.graphs = graph_registry

    # ══════════════════ 非流式主入口 ══════════════════
    async def handle(self, req: AgentRequest) -> AgentResponse:
        trace = start_trace(
            query=req.query,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            session_id=req.session_id,
            pipeline_mode=req.pipeline_mode,
        )
        try:
            async with span("orchestrator.handle", kind="orchestration"):
                route = await self._resolve_route(req)
                trace.route_level = route.level
                trace.route_reason = route.reason
                if route.reply_type == "social":
                    response = await self._social_reply(req)
                elif route.reply_type == "handover":
                    response = AgentResponse(
                        success=True,
                        content="已为您转接人工医师，请稍候。医生端会在收到会话后尽快接入。",
                        structured={"reply_type": "handover"},
                    )
                elif req.pipeline_mode:
                    response = await self._run_pipeline(req, trace)
                else:
                    response = await self._run_single_agent(req, route, trace)
                response.trace_id = trace.request_id
                response.route_level = route.level
                response.route_reason = route.reason
                response.latency_ms = trace.elapsed_ms
                response.tokens = trace.total_tokens
            finish_trace(
                status="success" if response.success else "failed",
                fallback_used=response.fallback_used,
                agent_type=response.agent_type.value if response.agent_type else "orchestrator",
                citations=len(response.citations),
                content_preview=response.content[:120],
            )
            return response
        except Exception as exc:  # noqa: BLE001  ── 第三层兜底：系统级
            log_event("orchestrator_error", error=repr(exc), request_id=trace.request_id)
            finish_trace(status="failed", fallback_used=True, agent_type="orchestrator", content_preview=str(exc)[:120])
            return AgentResponse(
                success=False,
                agent_type=req.agent_type,
                content="系统处理遇到问题，请稍后重试或联系管理员。",
                error=str(exc),
                trace_id=trace.request_id,
                fallback_used=True,
            )

    # ══════════════════ SSE 事件流 ══════════════════
    async def stream(self, req: AgentRequest) -> AsyncIterator[dict]:
        """事件结构与设计方案 §10.1 完全一致：route / node / tool_call / citation / delta / done。"""
        trace = start_trace(
            query=req.query,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            session_id=req.session_id,
            pipeline_mode=req.pipeline_mode,
        )
        try:
            route = await self._resolve_route(req)
            trace.route_level = route.level
            trace.route_reason = route.reason
            yield {
                "event": "route",
                "data": {
                    "agent_type": route.agent_type.value if route.agent_type else None,
                    "level": route.level,
                    "pipeline_mode": route.pipeline_mode,
                    "reply_type": route.reply_type,
                    "reason": route.reason,
                    "confidence": route.confidence,
                    "trace_id": trace.request_id,
                    "chips": route.suggestion_chips,
                },
            }

            if route.reply_type == "social":
                async for event in self._emit_answer(await self._social_reply(req), trace):
                    yield event
            elif route.reply_type == "handover":
                response = AgentResponse(
                    success=True, content="已为您转接人工医师，请稍候。", structured={"reply_type": "handover"}
                )
                async for event in self._emit_answer(response, trace):
                    yield event
            elif req.pipeline_mode:
                async for event in self._stream_pipeline(req, trace):
                    yield event
            else:
                async for event in self._stream_single_agent(req, route, trace):
                    yield event
        except Exception as exc:  # noqa: BLE001
            log_event("orchestrator_stream_error", error=repr(exc))
            finish_trace(status="failed", fallback_used=True, content_preview=str(exc)[:120])
            yield {"event": "error", "data": {"message": "系统处理遇到问题，请稍后重试。", "error": str(exc)}}
            yield {"event": "done", "data": {"success": False, "trace_id": trace.request_id, "fallback_used": True}}

    # ══════════════════ 路由 ══════════════════
    async def _resolve_route(self, req: AgentRequest) -> RouteResult:
        if req.agent_type:
            return RouteResult(
                agent_type=req.agent_type,
                pipeline_mode=req.pipeline_mode,
                level="L0",
                reason="按指定业务模块直达",
                confidence=1.0,
            )
        return await self.router.route(req.query, req.session_id)

    async def _social_reply(self, req: AgentRequest) -> AgentResponse:
        from ..agents.medqa.state import AnswerWithCitations

        result = await llm_factory.get("main").with_structured_output(AnswerWithCitations, task="chitchat").ainvoke(
            "", payload={"query": req.query}
        )
        return AgentResponse(
            success=True,
            content=result.answer,
            structured={
                "reply_type": "social",
                "chips": ["二甲双胍的禁忌症有哪些？", "帮我做病历质控", "我想挂号，最近胸闷"],
            },
        )

    # ══════════════════ 单 Agent 直达 ══════════════════
    async def _run_single_agent(self, req: AgentRequest, route: RouteResult, trace) -> AgentResponse:
        agent_type = route.agent_type or AgentType.MEDQA
        self.sessions.activate(req.session_id, agent_type)
        try:
            async with span(f"agent.{agent_type.value}", kind="agent", agent=agent_type.value):
                result = await with_retry(lambda: self._invoke(agent_type, req), label=f"agent.{agent_type.value}")
            response = self._to_response(agent_type, result)
            response.latency_ms = trace.elapsed_ms
            return response
        except Exception as exc:  # noqa: BLE001 ── 第二层：Agent 级降级
            log_event("agent_failed_fallback", agent=agent_type.value, error=repr(exc))
            return await self._agent_fallback(agent_type, req, exc)

    async def _invoke(self, agent_type: AgentType, req: AgentRequest) -> dict:
        graph = self.graphs.get(agent_type)
        if agent_type is AgentType.MEDQA:
            return await graph.ainvoke(
                {"query": req.query, "messages": [], "tenant_id": req.tenant_id, "web_results": []}
            )
        if agent_type is AgentType.MEDREVIEW:
            return await graph.ainvoke(
                {
                    "raw_document": req.query or req.context.get("record_text", ""),
                    "tenant_id": req.tenant_id,
                    "user_id": req.user_id,
                }
            )
        from ..agents.preconsult.graph import graph_config

        # Pipeline 场景：直接复用已完成的预问诊会话（Checkpointer 里的状态），不重跑之前节点
        upstream_session = req.context.get("preconsult_session_id")
        if upstream_session:
            patient_id = req.context.get("patient_id") or req.user_id
            snapshot = await graph.aget_state(graph_config(req.tenant_id, patient_id, upstream_session))
            values = dict(snapshot.values or {})
            if values.get("current_stage") in {"FINISHED", "HANDOVER"}:
                return values
        if req.context.get("draft_record_text"):
            # 直通路径：外部直接给一段病历草稿，等价于预问诊已完成
            text = req.context["draft_record_text"]
            return {
                "current_stage": "FINISHED",
                "handover": False,
                "draft_record": {
                    "draft_record_id": req.context.get("draft_record_id") or "draft_external",
                    "chief_complaint": req.context.get("chief_complaint", ""),
                    "history_of_present_illness": text,
                    "completeness_score": float(req.context.get("completeness_score", 100)),
                },
                "report": {
                    "completeness_score": float(req.context.get("completeness_score", 100)),
                    "summary": "由上游直接提供的病历草稿",
                },
            }

        config = graph_config(req.tenant_id, req.user_id, req.session_id)
        update = {"session_id": req.session_id, "tenant_id": req.tenant_id, "patient_id": req.user_id}
        if req.query:
            update["patient_message"] = req.query
        return await graph.ainvoke(update, config)

    def _to_response(self, agent_type: AgentType, result: dict) -> AgentResponse:
        if "__interrupt__" in result:
            alert = extract_interrupt(result)
            return AgentResponse(
                success=True,
                agent_type=agent_type,
                content="检测到需要医生立即评估的危急症状，预问诊流程已暂停，正在通知医生接管。",
                structured={"interrupt": alert, "awaiting_handover": True, "stage": result.get("current_stage")},
            )
        if agent_type is AgentType.MEDQA:
            return AgentResponse(
                success=True,
                agent_type=agent_type,
                content=result.get("answer", ""),
                structured={
                    "query_type": result.get("query_type"),
                    "confidence": result.get("confidence"),
                    "confidence_detail": result.get("confidence_detail"),
                    "retrieval_pipeline": result.get("retrieval_pipeline"),
                    "docs": result.get("reranked_docs", []),
                    "web_results": result.get("web_results", []),
                },
                citations=result.get("citations", []),
                fallback_used=bool(result.get("fallback_used")),
            )
        if agent_type is AgentType.MEDREVIEW:
            return AgentResponse(
                success=True,
                agent_type=agent_type,
                content=f"质控完成：综合评分 {result.get('overall_score')} 分（{result.get('grade')}），"
                f"共发现 {len(result.get('issues', []))} 条问题。",
                structured={
                    "review_id": result.get("review_id"),
                    "report": result.get("report"),
                    "issues": result.get("issues", []),
                    "structured_record": result.get("structured_record"),
                    "rule_results": result.get("rule_results", []),
                    "dimension_results": result.get("dimension_results", []),
                    "cross_doc_results": result.get("cross_doc_results", []),
                },
            )
        return AgentResponse(
            success=True,
            agent_type=agent_type,
            content=result.get("current_question") or result.get("summary") or "",
            structured={
                "session_id": result.get("session_id"),
                "stage": result.get("current_stage"),
                "stage_turn_count": result.get("stage_turn_count"),
                "filled_slots": result.get("filled_slots", {}),
                "slot_values": result.get("slot_values", {}),
                "quality": result.get("last_answer_quality"),
                "route": result.get("last_route"),
                "handover": result.get("handover", False),
                "draft_record": result.get("draft_record") or {},
                "report": result.get("report") or {},
                "handover_reason": result.get("handover_reason", []),
                "completeness_score": (result.get("draft_record") or {}).get("completeness_score"),
            },
        )

    async def _agent_fallback(self, agent_type: AgentType, req: AgentRequest, exc: Exception) -> AgentResponse:
        """第二层降级：各 Agent 自己的兜底逻辑。"""
        if agent_type is AgentType.MEDQA:
            return AgentResponse(
                success=True,
                agent_type=agent_type,
                content="知识检索链路暂时不可用，已切换为**降级模式**（未检索知识库，回答不含引用）。"
                f"请稍后重试，或直接联系临床药师／专科医师核实。\n（问题：{req.query}）",
                fallback_used=True,
                error=str(exc),
            )
        if agent_type is AgentType.MEDREVIEW:
            from ..agents.medreview.rules import run_rule_track

            raw = req.query or req.context.get("record_text", "")
            rules = run_rule_track({"course_notes": [], "record_type": "admission"}, raw)
            return AgentResponse(
                success=True,
                agent_type=agent_type,
                content="LLM 评审轨不可用，已输出**部分质控**（仅规则引擎轨结果）。",
                structured={"partial": True, "rule_results": rules, "dimension_results": [], "issues": []},
                fallback_used=True,
                error=str(exc),
            )
        return AgentResponse(
            success=True,
            agent_type=agent_type,
            content="预问诊服务暂时不可用，已切换为通用问题模板继续采集，请稍后重试。",
            structured={"partial": True, "fallback_template": True},
            fallback_used=True,
            error=str(exc),
        )

    # ══════════════════ 多 Agent Pipeline ══════════════════
    async def _run_pipeline(self, req: AgentRequest, trace) -> AgentResponse:
        spec = PIPELINES.get(req.pipeline_mode or "", PIPELINES["preconsult_review"])
        current_context = dict(req.context)
        steps: list[dict] = []
        abort: GateResult | None = None
        gate_records: list[dict] = []

        async with span("pipeline", kind="pipeline", mode=spec.mode):
            for agent_type in spec.agents:
                step_req = AgentRequest(
                    agent_type=agent_type,
                    pipeline_mode=None,
                    query=req.query,
                    session_id=req.session_id,
                    context=current_context,
                    tenant_id=req.tenant_id,
                    user_id=req.user_id,
                    user_role=req.user_role,
                )
                async with span(f"pipeline.step.{agent_type.value}", kind="pipeline_step"):
                    step_response = await self._run_single_agent(
                        step_req, RouteResult(agent_type=agent_type, level="PIPELINE"), trace
                    )
                structured = step_response.structured or {}
                steps.append(
                    {
                        "agent_type": agent_type.value,
                        "label": AGENT_META[agent_type.value]["label"],
                        "success": step_response.success,
                        "summary": step_response.content[:240],
                        "structured": safe_json(structured),
                        "elapsed_ms": step_response.latency_ms,
                    }
                )
                if not step_response.success:
                    break

                for gate in PIPELINE_GATES.get(spec.mode, []):
                    outcome = gate(current_context, structured)
                    gate_records.append({"gate": gate.__name__, "aborted": isinstance(outcome, GateResult)})
                    if isinstance(outcome, GateResult):
                        abort = outcome
                        break
                if abort:
                    break

                for src_key, dst_key in CONTEXT_MAPPING.get(agent_type, []):
                    value = structured.get(src_key)
                    if value is not None:
                        current_context[dst_key] = value

        if abort:
            response = self._build_abort_response(abort, steps)
        else:
            response = self._merge_pipeline_response(steps, current_context)
        response.structured["gates"] = gate_records
        response.structured["pipeline_mode"] = spec.mode
        response.latency_ms = trace.elapsed_ms
        return response

    def _build_abort_response(self, abort: GateResult, steps: list[dict]) -> AgentResponse:
        return AgentResponse(
            success=True,
            agent_type=AgentType.PRECONSULT,
            content=f"Pipeline 已中止：{abort.detail or abort.reason}。后续质控步骤未执行（门控是 Pipeline 的断路器）。",
            structured={"aborted": True, "reason": abort.reason, "detail": abort.detail, "steps": steps},
        )

    def _merge_pipeline_response(self, steps: list[dict], context: dict) -> AgentResponse:
        review = context.get("record_review_id")
        return AgentResponse(
            success=True,
            agent_type=AgentType.MEDREVIEW,
            content=f"联动完成：{len(steps)} 个步骤执行成功"
            + (f"，质控结果 {review}" if review else "")
            + f"，共传递 {len(context)} 项信息。",
            structured={"steps": steps, "context": safe_json(context)},
        )

    # ══════════════════ 流式实现 ══════════════════
    async def _stream_single_agent(self, req: AgentRequest, route: RouteResult, trace) -> AsyncIterator[dict]:
        agent_type = route.agent_type or AgentType.MEDQA
        self.sessions.activate(req.session_id, agent_type)
        graph = self.graphs.get(agent_type)
        state = self._build_state(agent_type, req)
        config = None
        if agent_type is AgentType.PRECONSULT:
            from ..agents.preconsult.graph import graph_config

            config = graph_config(req.tenant_id, req.user_id, req.session_id)

        final_state: dict = dict(state)
        async with span(f"agent.{agent_type.value}", kind="agent", agent=agent_type.value):
            async for chunk in graph.astream(state, config, stream_mode="updates"):
                for node, update in chunk.items():
                    yield {
                        "event": "node",
                        "data": {
                            "node": node,
                            "agent_type": agent_type.value,
                            "tokens": trace.total_tokens,
                            "elapsed_ms": trace.elapsed_ms,
                        },
                    }
                    if isinstance(update, dict):
                        final_state.update(update)

        for tool_span in [s for s in trace.spans if s.kind == "tool"]:
            yield {
                "event": "tool_call",
                "data": {
                    "tool": tool_span.name.replace("mcp.", ""),
                    "args": tool_span.meta.get("args", {}),
                    "elapsed_ms": round(tool_span.elapsed_ms, 2),
                    "ok": tool_span.ok,
                },
            }

        response = self._to_response(agent_type, final_state)
        for index, citation in enumerate(response.citations or [], start=1):
            yield {"event": "citation", "data": {"index": index, **citation}}
        if response.structured and response.structured.get("awaiting_handover"):
            yield {"event": "interrupt", "data": response.structured["interrupt"]}
        async for event in self._emit_answer(response, trace, final_state):
            yield event

    async def _stream_pipeline(self, req: AgentRequest, trace) -> AsyncIterator[dict]:
        yield {"event": "pipeline_start", "data": {"mode": req.pipeline_mode}}
        response = await self._run_pipeline(req, trace)
        for step in (response.structured or {}).get("steps", []):
            yield {"event": "pipeline_step", "data": step}
        async for event in self._emit_answer(response, trace):
            yield event

    async def _emit_answer(self, response: AgentResponse, trace, state: dict | None = None) -> AsyncIterator[dict]:
        """把最终答案切成 delta 逐段推送（真实模型下这里就是 token 流）。"""
        del state
        text = response.content or ""
        step = max(12, len(text) // 14) if text else 0
        for i in range(0, len(text), step):
            yield {"event": "delta", "data": {"text": text[i : i + step]}}
            await asyncio.sleep(0.01)
        finish_trace(
            status="success" if response.success else "failed",
            fallback_used=response.fallback_used,
            agent_type=response.agent_type.value if response.agent_type else "orchestrator",
            content_preview=text[:120],
            citations=len(response.citations),
        )
        yield {
            "event": "done",
            "data": {
                "success": response.success,
                "trace_id": trace.request_id,
                "fallback_used": response.fallback_used,
                "total_tokens": trace.total_tokens,
                "elapsed_ms": trace.elapsed_ms,
                "agent_type": response.agent_type.value if response.agent_type else None,
                "route_level": response.route_level,
                "route_reason": response.route_reason,
                "structured": safe_json(response.structured),
                "citations": response.citations,
                "content": text,
            },
        }

    def _build_state(self, agent_type: AgentType, req: AgentRequest) -> dict:
        if agent_type is AgentType.MEDQA:
            return {"query": req.query, "messages": [], "tenant_id": req.tenant_id, "web_results": []}
        if agent_type is AgentType.MEDREVIEW:
            return {
                "raw_document": req.query or req.context.get("record_text", ""),
                "tenant_id": req.tenant_id,
                "user_id": req.user_id,
            }
        state = {
            "session_id": req.session_id,
            "tenant_id": req.tenant_id,
            "patient_id": req.user_id,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if req.query:
            state["patient_message"] = req.query
        return state


def extract_interrupt(result: dict) -> dict:
    interrupts = result.get("__interrupt__") or []
    if not interrupts:
        return {}
    first = interrupts[0]
    value = getattr(first, "value", None)
    if value is None and isinstance(first, dict):
        value = first.get("value")
    return value if isinstance(value, dict) else {"value": value}


def safe_json(payload):
    """保证 SSE / JSON 可序列化（State 里可能含 LangChain Message 对象）。"""
    if payload is None:
        return None
    try:
        json.dumps(payload, ensure_ascii=False)
        return payload
    except (TypeError, ValueError):
        return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


orchestrator = Orchestrator()
