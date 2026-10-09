"""MedReview 图装配 —— 三轨并行 + 节点内并发（★★☆ 进阶级）。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import aggregate_node, extract_node, parse_node, persist_node, run_three_tracks_node
from .state import ReviewState


def build_medreview_graph():
    builder = StateGraph(ReviewState)
    builder.add_node("parse", parse_node)
    builder.add_node("extract", extract_node)
    builder.add_node("run_three_tracks", run_three_tracks_node)
    builder.add_node("aggregate", aggregate_node)
    builder.add_node("persist", persist_node)

    builder.add_edge(START, "parse")
    builder.add_edge("parse", "extract")
    builder.add_edge("extract", "run_three_tracks")
    builder.add_edge("run_three_tracks", "aggregate")
    builder.add_edge("aggregate", "persist")
    builder.add_edge("persist", END)
    return builder.compile()


MEDREVIEW_TOPOLOGY = {
    "agent": "medreview",
    "difficulty": "★★☆ 进阶级",
    "paradigm": "三轨分流 + 节点内并发",
    "nodes": [
        {"id": "parse", "label": "文档解析", "desc": "PDF / DOCX / 文本 → 纯文本", "kind": "code"},
        {"id": "extract", "label": "结构化提取", "desc": "Pydantic 强约束抽取病历要素", "kind": "llm"},
        {"id": "run_three_tracks", "label": "三轨并行", "desc": "asyncio.gather 并发三轨，LLM 轨内部再并发六维度", "kind": "concurrency"},
        {"id": "aggregate", "label": "Fan-in 汇总", "desc": "三轨结果统一成 IssueItem + 加权综合评分", "kind": "code"},
        {"id": "persist", "label": "持久化", "desc": "结果落库，半结构化载荷以 JSONB 存放", "kind": "db"},
    ],
    "edges": [
        {"from": "START", "to": "parse"},
        {"from": "parse", "to": "extract"},
        {"from": "extract", "to": "run_three_tracks"},
        {"from": "run_three_tracks", "to": "aggregate"},
        {"from": "aggregate", "to": "persist"},
        {"from": "persist", "to": "END"},
    ],
    "tracks": [
        {"id": "rule", "label": "轨1 规则引擎", "desc": "时效性 / 签名 / 必填项 —— 纯代码，零 Token，100% 准确"},
        {"id": "llm", "label": "轨2 LLM 评审", "desc": "完整 / 一致 / 诊断依据 / 用药合理性 / 逻辑 / 规范 —— 六维度并发"},
        {"id": "cross", "label": "轨3 数据比对", "desc": "医嘱 ↔ 病程 ↔ 检验 三方一致性 —— 结构化提取后逐项比对"},
    ],
}
