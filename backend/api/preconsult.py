"""预问诊接口 —— 状态机推进 + 医生接管（对应 interrupt 恢复）。"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from langgraph.types import Command

from ..agents.preconsult.graph import get_preconsult_graph, graph_config
from ..agents.preconsult.stages import MIN_TURNS, REQUIRED_SLOTS, SLOT_LABELS, STAGE_LABELS, STAGES
from ..infra.db import db
from ..observability.trace import finish_trace, start_trace
from .deps import RequestContext, get_request_context

router = APIRouter(prefix="/api/v1/preconsult", tags=["preconsult"])

PENDING_ALERTS: dict[str, dict] = {}
# 会话 → 主体映射：保证 thread_id 稳定（thread_id 里含 patient_id，
# 一旦前后两次请求传入的 patient_id 不一致，就会落到不同的 Checkpointer 线程上）
SESSIONS: dict[str, dict] = {}


class StartRequest(BaseModel):
    patient_id: str = ""
    patient_name: str = ""
    note: str = ""


class AnswerRequest(BaseModel):
    text: str


class HandoverRequest(BaseModel):
    action: str = "take_over"  # take_over | continue | refer_emergency
    doctor_id: str = ""
    note: str = ""


def _initial_state(ctx: RequestContext, session_id: str, patient_id: str) -> dict:
    return {
        "session_id": session_id,
        "tenant_id": ctx.tenant_id,
        "patient_id": patient_id,
        "current_stage": "WARMUP",
        "stage_turn_count": 0,
        "filled_slots": {},
        "slot_values": {},
        "followup_count": 0,
        "rephrase_count": 0,
        "turn_count": 0,
        "messages": [],
        "handover": False,
    }


def _view(result: dict, session_id: str) -> dict:
    return {
        "session_id": session_id,
        "stage": result.get("current_stage", "WARMUP"),
        "stage_label": STAGE_LABELS.get(result.get("current_stage", ""), ""),
        "stage_turn_count": result.get("stage_turn_count", 0),
        "question": result.get("current_question", ""),
        "quality": result.get("last_answer_quality"),
        "route": result.get("last_route"),
        "filled_slots": result.get("filled_slots", {}),
        "slot_values": result.get("slot_values", {}),
        "handover": bool(result.get("handover")),
        "handover_reason": result.get("handover_reason", []),
        "draft_record": result.get("draft_record") or {},
        "report": result.get("report") or {},
        "turn_count": result.get("turn_count", 0),
    }


def _resolve_patient(session_id: str, ctx: RequestContext, provided: str = "") -> str:
    """解析本次请求的 patient_id —— 优先用会话登记的主体，其次用显式参数。"""
    known = SESSIONS.get(session_id, {}).get("patient_id")
    if known:
        return known
    patient_id = provided or f"pat_{session_id}"
    SESSIONS[session_id] = {"patient_id": patient_id, "tenant_id": ctx.tenant_id}
    return patient_id


@router.get("/stages")
async def stages() -> dict:
    return {
        "stages": [
            {
                "id": stage,
                "label": STAGE_LABELS[stage],
                "min_turns": MIN_TURNS[stage],
                "required_slots": sorted(REQUIRED_SLOTS[stage]),
                "slot_labels": [SLOT_LABELS.get(s, s) for s in sorted(REQUIRED_SLOTS[stage])],
            }
            for stage in STAGES
        ],
        "note": "阶段判定为纯代码：轮数达标 且 必填槽位齐备，两个条件同时满足才推进",
    }


@router.post("/start")
async def start(body: StartRequest, ctx: RequestContext = Depends(get_request_context)) -> dict:
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    patient_id = body.patient_id or f"pat_{uuid.uuid4().hex[:8]}"
    SESSIONS[session_id] = {"patient_id": patient_id, "tenant_id": ctx.tenant_id, "name": body.patient_name}
    trace = start_trace(query="预问诊发起", tenant_id=ctx.tenant_id, user_id=ctx.user_id, session_id=session_id, agent_type="preconsult")
    graph = get_preconsult_graph()
    config = graph_config(ctx.tenant_id, patient_id, session_id)
    result = await graph.ainvoke(_initial_state(ctx, session_id, patient_id), config)
    finish_trace(agent_type="preconsult", content_preview=str(result.get("current_question"))[:120])
    view = _view(result, session_id)
    view["trace_id"] = trace.request_id
    view["patient_id"] = patient_id
    return view


@router.post("/{session_id}/answer")
async def answer(
    session_id: str,
    body: AnswerRequest,
    patient_id: str = "",
    ctx: RequestContext = Depends(get_request_context),
) -> dict:
    if session_id in PENDING_ALERTS:
        raise HTTPException(status_code=409, detail="该会话存在待处理的红旗告警，请医生先完成接管")
    patient_id = _resolve_patient(session_id, ctx, patient_id)
    graph = get_preconsult_graph()
    config = graph_config(ctx.tenant_id, patient_id, session_id)
    trace = start_trace(query=body.text, tenant_id=ctx.tenant_id, user_id=ctx.user_id, session_id=session_id, agent_type="preconsult")
    result = await graph.ainvoke({"patient_message": body.text}, config)

    if "__interrupt__" in result:
        from ..orchestrator.core import extract_interrupt

        alert = extract_interrupt(result)
        PENDING_ALERTS[session_id] = {"alert": alert, "tenant_id": ctx.tenant_id, "session_id": session_id}
        finish_trace(agent_type="preconsult", fallback_used=True, content_preview="红旗告警，流程已挂起")
        return {
            "session_id": session_id,
            "interrupted": True,
            "alert": alert,
            "stage": result.get("current_stage"),
            "trace_id": trace.request_id,
            "note": "图执行已通过 interrupt() 挂起，State 由 Checkpointer 完整保存，医生决策后从断点恢复，不会重跑之前的节点。",
        }

    finish_trace(agent_type="preconsult", content_preview=str(result.get("current_question", ""))[:120])
    view = _view(result, session_id)
    view["interrupted"] = False
    view["trace_id"] = trace.request_id
    view["patient_id"] = patient_id
    return view


@router.post("/{session_id}/handover")
async def handover(
    session_id: str,
    body: HandoverRequest,
    patient_id: str = "",
    ctx: RequestContext = Depends(get_request_context),
) -> dict:
    """医生接管 —— 对应 Command(resume=decision)，从 interrupt() 断点继续执行。"""
    patient_id = _resolve_patient(session_id, ctx, patient_id)
    graph = get_preconsult_graph()
    config = graph_config(ctx.tenant_id, patient_id, session_id)
    trace = start_trace(query=f"医生接管 {body.action}", tenant_id=ctx.tenant_id, user_id=body.doctor_id or ctx.user_id, session_id=session_id, agent_type="preconsult")
    result = await graph.ainvoke(
        Command(resume={"action": body.action, "doctor_id": body.doctor_id or ctx.user_id, "note": body.note}),
        config,
    )
    PENDING_ALERTS.pop(session_id, None)
    finish_trace(agent_type="preconsult", content_preview=f"接管完成：{body.action}")
    view = _view(result, session_id)
    view["status"] = "resumed"
    view["action"] = body.action
    view["next_stage"] = result.get("current_stage")
    view["trace_id"] = trace.request_id
    return view


@router.get("/alerts/pending")
async def pending_alerts(ctx: RequestContext = Depends(get_request_context)) -> dict:
    items = [v for v in PENDING_ALERTS.values() if v["tenant_id"] == ctx.tenant_id]
    return {"items": items, "total": len(items)}


@router.get("/{session_id}/record")
async def record(session_id: str, ctx: RequestContext = Depends(get_request_context)) -> dict:
    row = await db.fetch_one(
        "SELECT * FROM preconsult_record WHERE session_id = ? AND tenant_id = ?", (session_id, ctx.tenant_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="预问诊记录不存在")
    for key in ("filled_slots", "handover_reason", "draft_record"):
        if row.get(key):
            row[key] = json.loads(row[key])
    return row
