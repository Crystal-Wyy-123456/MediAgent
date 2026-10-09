"""二级意图路由：L1 规则前置拦截（零 Token）+ L2 LLM 意图分类（兜底）。

为什么不加第三级向量语义缓存：为了命中少量同义 Query 要多维护一套向量缓存和
一致性策略，命中率不稳定、性价比不划算；规则拦截已经吃掉了最高频的那部分请求。
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field, ValidationError

from ..infra.llm_factory import llm_factory
from ..observability.trace import span
from .schema import AGENT_META, AgentType, RouteResult

SOCIAL_WORDS = {"你好", "您好", "谢谢", "在吗", "hi", "hello", "辛苦了", "早上好", "再见", "帮助", "你能做什么"}
HANDOVER_WORDS = ("转人工", "找医生", "人工客服", "接通医生")

ROUTE_PROMPT = """你是 MediAgent 的意图路由器，请把用户输入分派给最合适的 Agent。

可用 Agent：
{agents}

用户输入：{query}
"""

AGENT_DESCRIPTIONS = "\n".join(f"- {k}（{v['name']}）：{v['label']}，{v['paradigm']}" for k, v in AGENT_META.items())


class RouteDecision(BaseModel):
    agent_type: str = Field(description="medqa / medreview / preconsult")
    pipeline_mode: str | None = None
    reason: str = ""
    confidence: float = 0.8


class SessionRegistry:
    """会话状态继承：已经在某个流程里，后续输入直接归属该 Agent。"""

    def __init__(self) -> None:
        self._active: dict[str, AgentType] = {}

    def activate(self, session_id: str, agent_type: AgentType) -> None:
        if session_id:
            self._active[session_id] = agent_type

    def get_active(self, session_id: str) -> AgentType | None:
        return self._active.get(session_id)

    def clear(self, session_id: str) -> None:
        self._active.pop(session_id, None)


class IntentRouter:
    def __init__(self, sessions: SessionRegistry) -> None:
        self.sessions = sessions
        self.llm = llm_factory.get("router")
        self._stats = {"L1": 0, "L2": 0, "L2-fallback": 0}

    def stats(self) -> dict:
        total = sum(self._stats.values()) or 1
        return {
            "counts": dict(self._stats),
            "l1_hit_rate": round(self._stats["L1"] / total, 4),
            "total": total,
        }

    async def route(self, query: str, session_id: str = "") -> RouteResult:
        async with span("orchestrator.route", kind="routing"):
            hit = self._rule_prefilter(query, session_id)
            if hit:
                self._stats["L1"] += 1
                return hit
            return await self._llm_route(query)

    def _rule_prefilter(self, query: str, session_id: str) -> RouteResult | None:
        q = query.strip()
        if len(q) <= 4 and q in SOCIAL_WORDS:
            return RouteResult(
                agent_type=None,
                level="L1",
                reply_type="social",
                reason="日常问候，直接回应",
                suggestion_chips=["二甲双胍的禁忌症有哪些？", "帮我做病历质控", "我想挂号，最近胸闷"],
            )
        if q.startswith(HANDOVER_WORDS):
            return RouteResult(
                agent_type=None, level="L1", reply_type="handover", reason="用户要求转人工"
            )
        active = self.sessions.get_active(session_id)
        if active and not _looks_like_new_task(q):
            return RouteResult(
                agent_type=active,
                level="L1",
                reply_type="continue",
                reason=f"会话已在「{AGENT_META[active.value]['label']}」流程中，继续该流程",
            )
        return None

    async def _llm_route(self, query: str) -> RouteResult:
        try:
            decision = await asyncio.wait_for(
                self.llm.with_structured_output(RouteDecision, task="route").ainvoke(
                    ROUTE_PROMPT.format(query=query, agents=AGENT_DESCRIPTIONS),
                    payload={"query": query},
                ),
                timeout=5.0,
            )
            self._stats["L2"] += 1
            return RouteResult(
                agent_type=AgentType(decision.agent_type),
                pipeline_mode=decision.pipeline_mode,
                level="L2",
                reason=decision.reason,
                confidence=decision.confidence,
                cost_tokens=int(len(query) / 1.6) + 120,
            )
        except (asyncio.TimeoutError, ValidationError, ValueError):
            # 降级：当作医学知识问答处理，保证用户体验不断线
            self._stats["L2-fallback"] += 1
            return RouteResult(
                agent_type=AgentType.MEDQA,
                level="L2-fallback",
                reason="问题分流响应超时，已按医学知识问答处理",
                confidence=0.5,
            )


def _looks_like_new_task(query: str) -> bool:
    return any(k in query for k in ["换个问题", "新的问题", "另外问", "再帮我查", "病历质控", "预问诊"])
