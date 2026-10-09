"""统一对话入口 —— SSE 流式返回。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..orchestrator.core import orchestrator
from ..orchestrator.schema import AgentRequest, AgentType
from .deps import RequestContext, get_request_context

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    query: str
    session_id: str = ""
    agent_type: AgentType | None = None
    pipeline_mode: str | None = None
    context: dict | None = None
    stream: bool = True


def _to_request(body: ChatRequest, ctx: RequestContext) -> AgentRequest:
    return AgentRequest(
        query=body.query,
        session_id=body.session_id or f"sess_{ctx.user_id}",
        agent_type=body.agent_type,
        pipeline_mode=body.pipeline_mode,
        context=body.context or {},
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        user_role=ctx.user_role,  # type: ignore[arg-type]
        stream=body.stream,
    )


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, ctx: RequestContext = Depends(get_request_context)):
    """SSE 事件流：route / node / tool_call / citation / interrupt / delta / done。"""
    req = _to_request(body, ctx)

    async def event_source():
        async for event in orchestrator.stream(req):
            payload = json.dumps(event["data"], ensure_ascii=False, default=str)
            yield f"event: {event['event']}\ndata: {payload}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/chat")
async def chat(body: ChatRequest, ctx: RequestContext = Depends(get_request_context)) -> dict:
    """非流式版本 —— 便于脚本调用与自动化测试。"""
    response = await orchestrator.handle(_to_request(body, ctx))
    return response.model_dump(mode="json")
