"""MedQA 图装配 —— 条件分支 + 单链路 RAG（★☆☆ 入门级）。

拓扑：
  classify ──KNOWLEDGE──▶ retrieve ──门控──▶ generate / web_search / refuse
          └─CHITCHAT ───▶ direct_answer
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
    classify_node,
    direct_answer_node,
    generate_node,
    hybrid_retrieve_node,
    refuse_node,
    route_by_confidence,
    route_by_query_type,
    web_search_node,
)
from .state import QAState


def build_medqa_graph():
    builder = StateGraph(QAState)
    builder.add_node("classify", classify_node)
    builder.add_node("retrieve", hybrid_retrieve_node)
    builder.add_node("generate", generate_node)
    builder.add_node("web_search", web_search_node)
    builder.add_node("refuse", refuse_node)
    builder.add_node("direct_answer", direct_answer_node)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify",
        route_by_query_type,
        {"retrieve": "retrieve", "direct_answer": "direct_answer"},
    )
    builder.add_conditional_edges(
        "retrieve",
        route_by_confidence,
        {"generate": "generate", "web_search": "web_search", "refuse": "refuse"},
    )
    builder.add_edge("generate", END)
    builder.add_edge("web_search", END)
    builder.add_edge("refuse", END)
    builder.add_edge("direct_answer", END)
    return builder.compile()


MEDQA_TOPOLOGY = {
    "agent": "medqa",
    "difficulty": "★☆☆ 入门级",
    "paradigm": "条件分支 + 单链路 RAG",
    "nodes": [
        {"id": "classify", "label": "Query 分类", "desc": "LLM 温度 0，输出 KNOWLEDGE / CHITCHAT", "kind": "llm"},
        {"id": "retrieve", "label": "混合检索 + 精排", "desc": "BGE-M3 稠密 + BM25 稀疏 → WeightedRanker → Cross-Encoder 精排", "kind": "retrieval"},
        {"id": "generate", "label": "生成 + 强制引用", "desc": "结构化输出答案与引用卡片", "kind": "llm"},
        {"id": "web_search", "label": "联网兜底", "desc": "知识库覆盖不足时走 MCP 联网搜索", "kind": "tool"},
        {"id": "refuse", "label": "拒答", "desc": "置信度低于阈值时拒答并建议转人工", "kind": "guard"},
        {"id": "direct_answer", "label": "直接回应", "desc": "寒暄类不检索，零向量开销", "kind": "llm"},
    ],
    "edges": [
        {"from": "START", "to": "classify"},
        {"from": "classify", "to": "retrieve", "label": "KNOWLEDGE"},
        {"from": "classify", "to": "direct_answer", "label": "CHITCHAT"},
        {"from": "retrieve", "to": "generate", "label": "置信度 ≥ 0.62"},
        {"from": "retrieve", "to": "web_search", "label": "0.42 ≤ 置信度 < 0.62"},
        {"from": "retrieve", "to": "refuse", "label": "置信度 < 0.42"},
        {"from": "generate", "to": "END"},
    ],
}
