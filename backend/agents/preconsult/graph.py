"""PreConsult 图装配 —— 有限状态机 + 人机协同中断（★★★ 挑战级）。

拓扑：
  START ─┬─(患者消息)─▶ evaluate_answer ▶ red_flag_check ─┬─ 红旗 ─▶ interrupt() ▶ save_memory(END)
         │                                                ├─ 追问 ─▶ followup ▶ save_memory(END)
         │                                                ├─ 换问法 ▶ rephrase ▶ save_memory(END)
         │                                                └─ 下一题 ▶ check_stage ─┬─ ask ▶ generate_question ▶ save_memory
         └─(会话首轮)──────────────────────────────────────────────────────────────┴─ finish ▶ summarize ▶ save_memory(END)
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ...memory.checkpointer import get_memory_saver
from .nodes import (
    check_stage_node,
    evaluate_answer_node,
    followup_node,
    generate_question_node,
    red_flag_check_node,
    rephrase_node,
    route_after_check_stage,
    route_after_red_flag,
    route_entry,
    save_memory_node,
    summarize_node,
)
from .state import PreConsultState


def build_preconsult_graph():
    builder = StateGraph(PreConsultState)
    builder.add_node("evaluate_answer", evaluate_answer_node)
    builder.add_node("red_flag_check", red_flag_check_node)
    builder.add_node("followup", followup_node)
    builder.add_node("rephrase", rephrase_node)
    builder.add_node("check_stage", check_stage_node)
    builder.add_node("generate_question", generate_question_node)
    builder.add_node("summarize", summarize_node)
    builder.add_node("save_memory", save_memory_node)

    builder.add_conditional_edges(
        START, route_entry, {"evaluate": "evaluate_answer", "ask": "generate_question"}
    )
    builder.add_edge("evaluate_answer", "red_flag_check")
    builder.add_conditional_edges(
        "red_flag_check",
        route_after_red_flag,
        {
            "handover": "save_memory",
            "followup": "followup",
            "rephrase": "rephrase",
            "next_question": "check_stage",
        },
    )
    builder.add_conditional_edges(
        "check_stage", route_after_check_stage, {"ask": "generate_question", "summarize": "summarize"}
    )
    builder.add_edge("followup", "save_memory")
    builder.add_edge("rephrase", "save_memory")
    builder.add_edge("generate_question", "save_memory")
    builder.add_edge("summarize", "save_memory")
    builder.add_edge("save_memory", END)

    return builder.compile(checkpointer=get_memory_saver("preconsult"))


_graph = None


def get_preconsult_graph():
    """懒加载：首次使用时才构建图（对应设计方案的图懒加载原则）。"""
    global _graph
    if _graph is None:
        _graph = build_preconsult_graph()
    return _graph


PRECONSULT_TOPOLOGY = {
    "agent": "preconsult",
    "difficulty": "★★★ 挑战级",
    "paradigm": "有限状态机 + 人机协同中断",
    "checkpointer": "MemorySaver（按 agent 类型独立，thread_id = tenant_patient_session）",
    "nodes": [
        {"id": "evaluate_answer", "label": "回答质量评估", "desc": "LLM 四档标签 + 槽位抽取", "kind": "llm"},
        {"id": "red_flag_check", "label": "红旗症状检测", "desc": "关键词组合 + LLM 二次兜底；命中则 interrupt() 挂起", "kind": "guard"},
        {"id": "followup", "label": "追问深挖", "desc": "回答质量高时追问，上限 2 次", "kind": "llm"},
        {"id": "rephrase", "label": "换问法重问", "desc": "未答上来时换同义表达，最多 1 次", "kind": "llm"},
        {"id": "check_stage", "label": "阶段判定（纯代码）", "desc": "轮数 ≥ 最小值 且 槽位齐备 → 推进；零 Token、可单测", "kind": "code"},
        {"id": "generate_question", "label": "生成问题", "desc": "LLM 按阶段生成自然提问", "kind": "llm"},
        {"id": "summarize", "label": "生成小结", "desc": "输出预问诊小结与病历草稿（含完整度评分）", "kind": "llm"},
        {"id": "save_memory", "label": "记忆管理", "desc": "滑动窗口 + 摘要压缩，落库", "kind": "db"},
    ],
    "edges": [
        {"from": "START", "to": "evaluate_answer", "label": "患者消息"},
        {"from": "START", "to": "generate_question", "label": "会话首轮"},
        {"from": "evaluate_answer", "to": "red_flag_check"},
        {"from": "red_flag_check", "to": "handover", "label": "命中红旗 → interrupt()"},
        {"from": "red_flag_check", "to": "followup", "label": "EXCELLENT 且追问 < 2"},
        {"from": "red_flag_check", "to": "rephrase", "label": "NO_ANSWER 且重问 < 1"},
        {"from": "red_flag_check", "to": "check_stage", "label": "其余"},
        {"from": "check_stage", "to": "generate_question", "label": "未满足推进条件"},
        {"from": "check_stage", "to": "summarize", "label": "推进到 FINISHED"},
        {"from": "generate_question", "to": "save_memory"},
        {"from": "summarize", "to": "save_memory"},
        {"from": "save_memory", "to": "END"},
    ],
    "stages": [
        {"id": "WARMUP", "label": "寒暄与身份确认", "min_turns": 1, "slots": ["patient_confirmed"]},
        {"id": "CHIEF_COMPLAINT", "label": "主诉与时长", "min_turns": 2, "slots": ["chief_complaint", "duration"]},
        {"id": "HISTORY", "label": "现病史", "min_turns": 3, "slots": ["onset", "symptoms", "aggravating_factors"]},
        {"id": "PAST_HISTORY", "label": "既往史与用药史", "min_turns": 2, "slots": ["past_disease", "medication"]},
        {"id": "SUMMARY", "label": "小结确认", "min_turns": 1, "slots": ["patient_ack"]},
    ],
}


def thread_id(tenant_id: str, patient_id: str, session_id: str) -> str:
    """thread_id 里包含 tenant_id，天然实现院区（租户）隔离。"""
    return f"tenant_{tenant_id}_patient_{patient_id}_session_{session_id}"


def graph_config(tenant_id: str, patient_id: str, session_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id(tenant_id, patient_id, session_id)}}
