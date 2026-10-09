"""MedQA 节点实现。

设计要点：
  · 分类节点（LLM 调用）与路由函数（纯代码）**拆开** —— 路由 100% 可单测
  · 检索走 MCP 工具（混合检索 + 精排），Agent 不 import 检索实现
  · 置信度三向门控：生成 / 联网兜底 / 拒答（医疗场景：宁可拒答，不可幻觉）
"""

from __future__ import annotations

from ...config import settings
from ...observability.trace import traced
from ...tools.registry import mcp_registry
from .prompts import ANSWER_PROMPT, CLASSIFY_PROMPT, format_docs
from .state import AnswerWithCitations, QAState, QueryType, llm


@traced("node.classify", kind="node", model="router")
async def classify_node(state: QAState) -> dict:
    """判断这是「知识类问题」还是「寒暄」。只分两类，不分更细。"""
    query = state["query"]
    result = await llm.with_structured_output(QueryType, task="classify").ainvoke(
        CLASSIFY_PROMPT.format(query=query),
        payload={"query": query},
    )
    return {"query_type": result.type, "fallback_used": False}


def route_by_query_type(state: QAState) -> str:
    """条件路由函数 —— 纯代码，不调 LLM，给定状态必然得到确定分支。"""
    return {"KNOWLEDGE": "retrieve", "CHITCHAT": "direct_answer"}[state.get("query_type", "KNOWLEDGE")]


@traced("node.hybrid_retrieve", kind="node")
async def hybrid_retrieve_node(state: QAState) -> dict:
    """混合检索 + 精排：通过 MCP 工具调用，Agent 与检索实现解耦。"""
    query = state["query"]
    result = await mcp_registry.call(
        "search_guideline",
        {"query": query, "top_k": settings.retrieval_top_k},
    )
    docs = result.get("hits", [])
    return {
        "retrieved_docs": docs,
        "reranked_docs": docs,
        "confidence": result.get("confidence", 0.0),
        "confidence_detail": result.get("confidence_detail", {}),
        "retrieval_pipeline": result.get("pipeline", {}),
    }


def route_by_confidence(state: QAState) -> str:
    """三向门控：生成 / 联网兜底 / 拒答。"""
    docs = state.get("reranked_docs") or []
    conf = float(state.get("confidence") or 0.0)
    if not docs or len(docs) < settings.min_docs:
        return "web_search"
    if conf < settings.confidence_refuse:
        return "refuse"  # 医疗场景：宁可拒答，不可幻觉
    if conf < settings.confidence_generate:
        return "web_search"  # 知识库覆盖不足，外部补充
    return "generate"


@traced("node.generate", kind="node")
async def generate_node(state: QAState) -> dict:
    """生成答案，并把引用来源结构化输出（可溯源是硬约束）。"""
    docs = state.get("reranked_docs") or []
    rules = "每条结论必须标注来源编号；无来源支撑的结论不得输出。"
    result = await llm.with_structured_output(AnswerWithCitations, task="answer").ainvoke(
        ANSWER_PROMPT.format(context=format_docs(docs), query=state["query"], rules=rules),
        payload={"query": state["query"], "docs": docs, "rules": rules},
    )
    return {
        "answer": result.answer,
        "citations": [c.model_dump() for c in result.citations],
        "fallback_used": False,
    }


@traced("node.web_search", kind="node")
async def web_search_node(state: QAState) -> dict:
    """知识库覆盖不足 → MCP 联网搜索兜底，并显式标记 fallback_used。"""
    result = await mcp_registry.call("web_search", {"query": state["query"], "max_results": 3})
    items = result.get("results", [])
    if not items:
        return await refuse_node(state, reason="知识库与联网检索均未获得可靠依据")
    lines = [f"[{i}] {item['title']}\n    {item['snippet']}" for i, item in enumerate(items, start=1)]
    answer = (
        f"院内知识库对「{state['query']}」的覆盖不足，已触发联网兜底检索。以下为外部线索，"
        "**未经院内知识库校验，请勿直接作为诊疗依据**：\n\n" + "\n".join(lines)
    )
    return {"answer": answer, "citations": [], "web_results": items, "fallback_used": True}


@traced("node.refuse", kind="node")
async def refuse_node(state: QAState, reason: str | None = None) -> dict:
    """低置信度拒答 —— 医疗场景的核心安全设计。"""
    detail = state.get("confidence_detail") or {}
    reason = reason or "检索置信度低于拒答阈值"
    result = await llm.with_structured_output(AnswerWithCitations, task="refuse").ainvoke(
        "",
        payload={
            "query": state["query"],
            "reason": reason,
            "confidence": state.get("confidence", 0.0),
            "detail": detail,
            "docs": [],
        },
    )
    return {"answer": result.answer, "citations": [], "fallback_used": True}


@traced("node.direct_answer", kind="node")
async def direct_answer_node(state: QAState) -> dict:
    """寒暄类直接回应，不检索、零向量开销。"""
    result = await llm.with_structured_output(AnswerWithCitations, task="chitchat").ainvoke(
        "",
        payload={"query": state["query"]},
    )
    return {"answer": result.answer, "citations": [], "fallback_used": False}
