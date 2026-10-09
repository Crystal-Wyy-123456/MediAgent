"""统一契约 —— 所有 Agent 都吃 AgentRequest，任何情况下都返回 AgentResponse。"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    MEDQA = "medqa"          # 医学知识问答
    MEDREVIEW = "medreview"  # 病历质控
    PRECONSULT = "preconsult"  # 预问诊


AGENT_META = {
    "medqa": {"name": "MedQA", "label": "医学知识问答", "difficulty": "★☆☆ 入门级", "paradigm": "条件分支 + 单链路 RAG"},
    "medreview": {"name": "MedReview", "label": "病历内涵质控", "difficulty": "★★☆ 进阶级", "paradigm": "三轨并行 + 节点内并发"},
    "preconsult": {"name": "PreConsult", "label": "门诊预问诊", "difficulty": "★★★ 挑战级", "paradigm": "有限状态机 + 人机协同中断"},
}


class AgentRequest(BaseModel):
    """统一入参契约"""

    agent_type: AgentType | None = None
    pipeline_mode: str | None = None
    query: str = ""
    session_id: str = ""
    context: dict = Field(default_factory=dict)
    tenant_id: str = "tnt_renhe"
    user_id: str = "u_default"
    user_role: Literal["doctor", "qc_staff", "patient", "admin"] = "doctor"
    stream: bool = True


class AgentResponse(BaseModel):
    """统一出参契约 —— 保证任何情况下都返回它，绝不向上抛异常"""

    success: bool = True
    agent_type: AgentType | None = None
    content: str = ""
    structured: dict | None = None
    citations: list[dict] = Field(default_factory=list)
    fallback_used: bool = False
    error: str | None = None
    trace_id: str = ""
    latency_ms: float = 0.0
    route_level: str = ""
    route_reason: str = ""
    tokens: int = 0


class RouteResult(BaseModel):
    """路由结果"""

    agent_type: AgentType | None = None
    pipeline_mode: str | None = None
    level: str = "L2"
    reason: str = ""
    reply_type: str | None = None  # social | handover | continue
    confidence: float = 0.0
    cost_tokens: int = 0
    suggestion_chips: list[str] = Field(default_factory=list)
