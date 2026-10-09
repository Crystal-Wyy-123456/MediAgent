"""深度编排接口 —— 预问诊 → 病历质控 全链路（带门控与显式字段映射）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..infra.db import db
from ..orchestrator.core import orchestrator, safe_json
from ..orchestrator.pipeline import CONTEXT_MAPPING, PIPELINE_GATES, PIPELINES
from ..orchestrator.schema import AgentRequest
from .deps import RequestContext, get_request_context

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


class PipelineRequest(BaseModel):
    session_id: str = ""
    patient_id: str = ""
    text: str = ""
    chief_complaint: str = ""


def _draft_to_record_text(draft: dict, summary: str = "") -> str:
    """把预问诊的结构化草稿还原成一份「入院记录」文本，供质控 Agent 使用。"""
    name = draft.get("patient_name") or "患者"
    lines = [
        f"【姓名】{name}　【性别】{draft.get('gender', '')}　【年龄】{draft.get('age', '')}　【科室】门诊",
        f"【主诉】{draft.get('chief_complaint', '')}",
        f"【现病史】{draft.get('history_of_present_illness', '')}",
        f"【既往史】{draft.get('past_history', '')}",
        f"【过敏史】{draft.get('allergy_history', '')}",
        "【体格检查】（预问诊未采集，需医师补充）",
        "【辅助检查】（预问诊未采集，需医师补充）",
        "【初步诊断】（待医师补充）",
        "【诊疗计划】（待医师补充）",
        f"【病程记录】预问诊小结：{summary}",
        "【医师签名】",
        "【住院医师签名】",
    ]
    return "\n".join(lines)


@router.post("/preconsult-review")
async def preconsult_review(body: PipelineRequest, ctx: RequestContext = Depends(get_request_context)) -> dict:
    context: dict = {}
    query = body.text or ""

    if body.session_id:
        row = await db.fetch_one(
            "SELECT draft_record, summary, handover FROM preconsult_record WHERE session_id = ? AND tenant_id = ?",
            (body.session_id, ctx.tenant_id),
        )
        if row and row.get("draft_record"):
            draft = json.loads(row["draft_record"])
            context.update(
                {
                    "preconsult_session_id": body.session_id,
                    "patient_id": body.patient_id or f"pat_{body.session_id}",
                    "draft_record_text": (row.get("summary") or "") + "\n" + _draft_to_record_text(draft, row.get("summary") or ""),
                    "draft_record": draft,
                    "completeness_score": draft.get("completeness_score", 100),
                    "handover": bool(row.get("handover")),
                }
            )
            query = context["draft_record_text"]

    if not query:
        return {
            "success": False,
            "content": "请提供已完成的预问诊 session_id，或直接给出一段病历文本（text）。",
            "structured": {"steps": [], "hint": "先跑完 /api/v1/preconsult/start + answer 全流程，再用它的 session_id 调本接口"},
        }

    response = await orchestrator.handle(
        AgentRequest(
            pipeline_mode="preconsult_review",
            query=query,
            session_id=body.session_id or "pipe_default",
            context=context,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            user_role=ctx.user_role,  # type: ignore[arg-type]
        )
    )
    payload = response.model_dump(mode="json")
    payload["structured"] = safe_json(payload["structured"])
    payload["pipeline"] = {
        "mode": "preconsult_review",
        "path": [a.value for a in PIPELINES["preconsult_review"].agents],
        "gates": [g.__name__ for g in PIPELINE_GATES["preconsult_review"]],
        "mapping": {a.value: [list(p) for p in pairs] for a, pairs in CONTEXT_MAPPING.items()},
    }
    return payload


@router.get("/topology")
async def topology() -> dict:
    from ..orchestrator.pipeline import pipeline_topology

    return {"items": pipeline_topology()}
