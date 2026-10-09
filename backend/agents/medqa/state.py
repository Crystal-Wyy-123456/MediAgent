"""MedQA 的共享数据总线 —— 11 个字段，简单 Agent 就该有简单的 State。"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

from ...infra.llm_factory import llm_factory
from pydantic import BaseModel, Field


class QueryType(BaseModel):
    """Query 分类结果：只分两类，分出来的类别不走不同链路就是无效复杂度。"""

    type: str = Field(description="KNOWLEDGE 或 CHITCHAT")
    reason: str = Field(default="", description="分类依据")


class Citation(BaseModel):
    index: int
    source: str = ""
    chapter: str = ""
    page: int | None = None
    snippet: str = ""


class AnswerWithCitations(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    refusal: bool = False


class QAState(TypedDict, total=False):
    """MedQA 的共享数据总线 —— 所有节点读写同一个 State。"""

    messages: Annotated[list, add_messages]  # reducer：追加而非覆盖

    # ── 分类 ──
    query: str
    query_type: str  # KNOWLEDGE | CHITCHAT

    # ── 检索 ──
    retrieved_docs: list[dict]  # 双路召回 + 融合的原始结果
    reranked_docs: list[dict]  # 精排后 Top-K
    confidence: float
    confidence_detail: dict
    retrieval_pipeline: dict

    # ── 兜底 ──
    web_results: list[dict]
    fallback_used: bool

    # ── 生成 ──
    answer: str
    citations: list[dict]

    # ── 隔离 ──
    tenant_id: str


llm = llm_factory.get("main")
router_llm = llm_factory.get("router")
