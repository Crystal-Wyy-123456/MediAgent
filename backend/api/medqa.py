"""MedQA 专用接口 —— 医生工作站内嵌调用（非流式）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..orchestrator.core import orchestrator
from ..orchestrator.schema import AgentRequest, AgentType
from .deps import RequestContext, get_request_context

router = APIRouter(prefix="/api/v1/medqa", tags=["medqa"])


class AskRequest(BaseModel):
    query: str
    session_id: str = ""
    top_k: int | None = None


@router.post("/ask")
async def ask(body: AskRequest, ctx: RequestContext = Depends(get_request_context)) -> dict:
    response = await orchestrator.handle(
        AgentRequest(
            agent_type=AgentType.MEDQA,
            query=body.query,
            session_id=body.session_id or f"sess_{ctx.user_id}",
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            user_role=ctx.user_role,  # type: ignore[arg-type]
        )
    )
    return response.model_dump(mode="json")
