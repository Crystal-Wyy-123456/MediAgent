"""私有化推理引擎 —— 复刻云端模型在每个节点上的输出契约与判据。

分层：
  router.py     意图分类 / 路由决策
  medqa.py      知识问答生成 + 拒答 + 寒暄
  medreview.py  六个质控维度的语义判断 + 结构化提取
  preconsult.py 问诊提问 / 回答质量评估 / 小结 / 上下文压缩
"""

from __future__ import annotations

from . import medqa, medreview, preconsult, router

_STRUCTURED = {
    "QueryType": router.query_type,
    "RouteDecision": router.route_decision,
    "AnswerWithCitations": medqa.answer_with_citations,
    "Refusal": medqa.refusal,
    "ExtractedRecord": medreview.extract_record,
    "DimensionResult": medreview.dimension_result,
    "AnswerQuality": preconsult.answer_quality,
    "RedFlagJudgement": preconsult.red_flag_judgement,
}

_TEXT = {
    "chitchat": medqa.chitchat,
    "direct_answer": medqa.chitchat,
    "generate_question": preconsult.generate_question,
    "rephrase_question": preconsult.rephrase_question,
    "followup_question": preconsult.followup_question,
    "summarize": preconsult.summarize,
    "patient_summary": preconsult.patient_summary,
    "compress": preconsult.compress,
    "doctor_note": preconsult.doctor_note,
    "generic": medqa.chitchat,
}


def run_structured(schema_name: str, payload: dict) -> dict:
    # 同一个 Schema 在不同节点承载不同语义，用 task 区分（云端模型靠 Prompt 区分）
    task = payload.get("__task__")
    if task == "chitchat":
        return {"answer": medqa.chitchat(payload), "citations": [], "refusal": False}
    if task == "refuse":
        result = medqa.refusal(payload)
        return {"answer": result["answer"], "citations": [], "refusal": True}

    fn = _STRUCTURED.get(schema_name)
    if fn is None:
        raise KeyError(f"内置引擎未实现的结构化输出：{schema_name}")
    return fn(payload)


def run_text(task: str, payload: dict, prompt: str = "") -> str:
    fn = _TEXT.get(task)
    if fn is None:
        return f"[内置引擎] 已处理任务 {task}。"
    return fn(payload, prompt)
