"""PreConsult 节点实现 —— 有限状态机 + 人机协同中断。

核心设计原则：**阶段控制与内容生成分离**
  · 阶段推进（现在该问什么、能不能结束）→ 纯代码（check_stage_node），确定性、零 Token、可单测
  · 内容生成（这个阶段该怎么说）      → LLM，需要语言灵活性
"""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from ...config import settings
from ...infra.db import db
from ...infra.llm_factory import llm_factory
from ...observability.trace import traced
from .prompts import EVAL_PROMPT, FOLLOWUP_PROMPT, QUESTION_PROMPT, RED_FLAG_PROMPT, REPHRASE_PROMPT
from .red_flags import detect_red_flags, needs_llm_double_check
from .stages import REQUIRED_SLOTS, SLOT_LABELS, STAGE_LABELS, SLOT_OWNER as STAGE_SLOT_OWNER, evaluate_stage
from .state import AnswerQuality, PreConsultState, RedFlagJudgement

llm = llm_factory.get("main")

# 一经采集不再覆盖的槽位（现病史类：主诉、时长、起病、症状、加重缓解因素）
STICKY_SLOTS = {"chief_complaint", "duration", "onset", "symptoms", "aggravating_factors"}


@traced("node.evaluate_answer", kind="node")
async def evaluate_answer_node(state: PreConsultState) -> dict:
    """用 LLM 给患者回答打质量标签并抽取槽位（这一步必须用 LLM，需要语义理解）。"""
    stage = state.get("current_stage", "WARMUP")
    answer = state.get("patient_message", "") or ""
    result = await llm.with_structured_output(AnswerQuality, task="quality").ainvoke(
        EVAL_PROMPT.format(stage=stage, question=state.get("current_question", ""), answer=answer),
        payload={"answer": answer, "stage": stage, "question": state.get("current_question", "")},
    )

    filled = {k: list(v) for k, v in (state.get("filled_slots") or {}).items()}
    values = dict(state.get("slot_values") or {})
    for key, value in (result.extracted_slots or {}).items():
        if value in (None, "", False, []):
            continue
        # 现病史类槽位「先到先得」：后续病史里的「高血压5年」不能覆盖主诉时长；
        # 既往史/用药史允许补充修正（患者会陆续想起更多信息）
        if key in STICKY_SLOTS and values.get(key):
            continue
        # 槽位归到它**所属**的阶段：患者提前提供的信息同样有效
        owner = STAGE_SLOT_OWNER.get(key, stage)
        bucket = set(filled.get(owner, []))
        bucket.add(key)
        filled[owner] = sorted(bucket)
        values[key] = value

    return {
        "last_answer_quality": result.grade,
        "filled_slots": filled,
        "slot_values": values,
        "stage_turn_count": int(state.get("stage_turn_count", 0)) + 1,
        "messages": [HumanMessage(content=answer)] if answer else [],
    }


def _recent_patient_text(state: PreConsultState, current: str, n: int = 4) -> str:
    """把最近几轮患者原话合并后再判断：分两轮说出的症状也能组合命中。"""
    history = [
        message.content
        for message in (state.get("messages") or [])
        if isinstance(message, HumanMessage) and message.content
    ][-n:]
    if not any(current in item for item in history):
        history.append(current)
    return "。".join(history)


@traced("node.red_flag_check", kind="node")
async def red_flag_check_node(state: PreConsultState) -> dict:
    """红旗症状检测。命中后通过 interrupt() 挂起图执行，把决策权交给医生。"""
    text = state.get("patient_message") or ""
    if not text:
        return {"handover": False}

    scan_text = _recent_patient_text(state, text)
    hits = detect_red_flags(scan_text)
    judgement_reason = "识别到需要医生立即关注的症状"
    if not hits and needs_llm_double_check(scan_text, hits):
        judgement = await llm.with_structured_output(RedFlagJudgement, task="redflag").ainvoke(
            RED_FLAG_PROMPT.format(text=scan_text),
            payload={"text": scan_text},
        )
        if judgement.hit:
            hits = [
                {"name": f"llm_semantic_{i}", "label": flag, "advice": "由医生评估是否需要急诊处置。", "severity": "high"}
                for i, flag in enumerate(judgement.flags or ["语义识别的高危症状"])
            ]
            judgement_reason = f"系统综合判断：{judgement.reason}"

    if not hits:
        return {"handover": False, "red_flag_alert": {}}

    alert = {
        "type": "RED_FLAG_ALERT",
        "flags": hits,
        "patient_summary": _patient_summary(state, text),
        "transcript": _recent_messages(state, n=6),
        "options": ["take_over", "continue", "refer_emergency"],
        "reason": judgement_reason,
        "stage": state.get("current_stage", ""),
        "raised_at": time.time(),
    }

    # ★ 关键调用：图在此处暂停，State 被 Checkpointer 完整序列化保存，不占线程
    decision = interrupt(alert)

    # ── 下面这段是「恢复执行」后才会走到的代码 ──
    action = (decision or {}).get("action", "continue")
    if action in {"take_over", "refer_emergency"}:
        return {
            "handover": True,
            "handover_reason": [h.get("label", h.get("name", "")) for h in hits],
            "handover_note": (decision or {}).get("note", ""),
            "doctor_id": (decision or {}).get("doctor_id", ""),
            "red_flag_alert": alert,
            "current_stage": "HANDOVER",
        }
    return {
        "handover": False,
        "handover_note": (decision or {}).get("note", ""),
        "red_flag_alert": alert,
    }


def route_after_red_flag(state: PreConsultState) -> str:
    """红旗优先，其次才是追问/换题 —— 路由完全在代码层，不依赖 LLM。"""
    if state.get("handover"):
        return "handover"
    grade = state.get("last_answer_quality", "ADEQUATE")
    if grade == "EXCELLENT" and int(state.get("followup_count", 0)) < settings.max_followup:
        return "followup"
    if grade == "NO_ANSWER" and int(state.get("rephrase_count", 0)) < 1:
        return "rephrase"
    return "next_question"


@traced("node.followup", kind="node")
async def followup_node(state: PreConsultState) -> dict:
    """回答质量高 → 深挖一层（上限 2 次，规则在代码层）。"""
    question = await llm.ainvoke(
        FOLLOWUP_PROMPT.format(stage=state.get("current_stage", ""), answer=state.get("patient_message", "")),
        task="followup_question",
        payload={"stage": state.get("current_stage"), "answer": state.get("patient_message", "")},
    )
    return {
        "current_question": question.content,
        "followup_count": int(state.get("followup_count", 0)) + 1,
        "last_route": "followup",
        "messages": [AIMessage(content=question.content)],
    }


@traced("node.rephrase", kind="node")
async def rephrase_node(state: PreConsultState) -> dict:
    """患者没答上来 → 换同义表达重问一次（最多 1 次）。"""
    question = await llm.ainvoke(
        REPHRASE_PROMPT.format(question=state.get("current_question", ""), stage=state.get("current_stage", "")),
        task="rephrase_question",
        payload={"stage": state.get("current_stage"), "question": state.get("current_question", "")},
    )
    return {
        "current_question": question.content,
        "rephrase_count": int(state.get("rephrase_count", 0)) + 1,
        "last_route": "rephrase",
        "messages": [AIMessage(content=question.content)],
    }


@traced("node.check_stage", kind="node")
async def check_stage_node(state: PreConsultState) -> dict:
    """★ 纯代码阶段判定 —— 零 Token 消耗，100% 可单元测试。"""
    stage = state.get("current_stage", "WARMUP")
    outcome = evaluate_stage(stage, int(state.get("stage_turn_count", 0)), state.get("filled_slots") or {})
    if not outcome["advanced"]:
        return {"stage_decision": outcome}
    return {
        "current_stage": outcome["next_stage"],
        "stage_turn_count": 0,
        "followup_count": 0,
        "rephrase_count": 0,
        "stage_decision": outcome,
    }


def route_after_check_stage(state: PreConsultState) -> str:
    return "summarize" if state.get("current_stage") == "FINISHED" else "ask"


@traced("node.generate_question", kind="node")
async def generate_question_node(state: PreConsultState) -> dict:
    """内容生成用 LLM —— 问法自然，患者体验好。"""
    stage = state.get("current_stage", "WARMUP")
    required = REQUIRED_SLOTS.get(stage, set())
    filled = set((state.get("filled_slots") or {}).get(stage, []))
    missing = sorted(required - filled)
    question = await llm.ainvoke(
        QUESTION_PROMPT.format(
            stage=stage,
            slots="、".join(SLOT_LABELS.get(s, s) for s in sorted(filled)) or "无",
            missing="、".join(SLOT_LABELS.get(s, s) for s in missing) or "无",
        ),
        task="generate_question",
        payload={
            "stage": stage,
            "filled_slots": state.get("filled_slots") or {},
            "missing_slots": missing,
            "first_turn": int(state.get("turn_count", 0)) == 0,
        },
    )
    return {
        "current_question": question.content,
        "last_route": "ask",
        "messages": [AIMessage(content=question.content)],
    }


@traced("node.summarize", kind="node")
async def summarize_node(state: PreConsultState) -> dict:
    """生成预问诊小结与病历草稿，并给出完整度评分（供 Pipeline 门控使用）。"""
    values = state.get("slot_values") or {}
    summary = await llm.ainvoke(
        "把预问诊采集到的信息整理成小结",
        task="summarize",
        payload={"filled_slots": state.get("filled_slots") or {}, "slot_values": values},
    )
    required = ["chief_complaint", "duration", "onset", "symptoms", "aggravating_factors", "past_disease", "medication", "allergy"]
    filled_count = sum(1 for key in required if values.get(key))
    completeness = round(filled_count / len(required) * 100, 1)
    draft = {
        "draft_record_id": f"draft_{state.get('session_id', 'unknown')}",
        "patient_name": values.get("patient_name", ""),
        "gender": values.get("gender", ""),
        "age": values.get("age", ""),
        "chief_complaint": f"{values.get('chief_complaint', '未明确')} {values.get('duration', '')}".strip(),
        "history_of_present_illness": state.get("history_of_present_illness")
        or "；".join(
            filter(
                None,
                [
                    f"起病时间：{values['onset']}" if values.get("onset") else "",
                    f"症状特点：{values['symptoms']}" if values.get("symptoms") else "",
                    f"加重/缓解因素：{values['aggravating_factors']}" if values.get("aggravating_factors") else "",
                ],
            )
        ),
        "past_history": values.get("past_disease", ""),
        "medication_history": values.get("medication", ""),
        "allergy_history": values.get("allergy", ""),
        "completeness_score": completeness,
        "handover": bool(state.get("handover")),
    }
    return {
        "summary": summary.content,
        "current_question": summary.content,
        "draft_record": draft,
        "report": {
            "session_id": state.get("session_id"),
            "summary": summary.content,
            "completeness_score": completeness,
            "turn_count": state.get("turn_count", 0),
            "handover": bool(state.get("handover")),
        },
        "messages": [AIMessage(content=summary.content)],
        "last_route": "summarize",
    }


@traced("node.save_memory", kind="node")
async def save_memory_node(state: PreConsultState) -> dict:
    """上下文长度控制：未超阈值只做滑动窗口；超阈值触发摘要压缩。"""
    messages = state.get("messages") or []
    update: dict = {"turn_count": int(state.get("turn_count", 0)) + 1}

    if len(messages) > settings.compress_threshold:
        to_compress = messages[: -settings.keep_recent]
        history = [getattr(m, "content", "") for m in to_compress]
        compressed = await llm.ainvoke("压缩历史问诊记录", task="compress", payload={"history": history})
        from langchain_core.messages import SystemMessage

        update["messages"] = [SystemMessage(content=f"[历史问诊摘要]\n{compressed.content}"), *messages[-settings.keep_recent :]]
        update["summary"] = compressed.content
        update["compressed"] = True

    await _persist_record(state, update)
    return update


async def _persist_record(state: PreConsultState, update: dict) -> None:
    import json

    values = state.get("slot_values") or {}
    draft = state.get("draft_record") or {}
    await db.execute(
        """INSERT OR REPLACE INTO preconsult_record
           (record_id, session_id, tenant_id, patient_id, current_stage, filled_slots, chief_complaint,
            hpi, past_history, medication_history, allergy_history, completeness_score, handover,
            handover_reason, handover_doctor_id, draft_record, summary, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            f"pre_{state.get('session_id', 'unknown')}",
            state.get("session_id", ""),
            state.get("tenant_id", ""),
            state.get("patient_id", ""),
            state.get("current_stage", ""),
            json.dumps(state.get("filled_slots") or {}, ensure_ascii=False),
            draft.get("chief_complaint") or values.get("chief_complaint", ""),
            draft.get("history_of_present_illness", ""),
            draft.get("past_history", ""),
            draft.get("medication_history", ""),
            draft.get("allergy_history", ""),
            draft.get("completeness_score"),
            1 if state.get("handover") else 0,
            json.dumps(state.get("handover_reason") or [], ensure_ascii=False),
            state.get("doctor_id", ""),
            json.dumps(draft, ensure_ascii=False),
            update.get("summary") or state.get("summary", ""),
            time.time(),
        ),
    )


def route_entry(state: PreConsultState) -> str:
    """入口分流：患者发了消息就走评估，否则直接提问（会话首轮）。"""
    return "evaluate" if (state.get("patient_message") or "").strip() else "ask"


def _patient_summary(state: PreConsultState, text: str) -> str:
    values = state.get("slot_values") or {}
    stage = state.get("current_stage", "")
    return (
        f"患者：{values.get('patient_name', '未填写')} {values.get('gender', '')} {values.get('age', '')}\n"
        f"主诉：{values.get('chief_complaint', '未明确')} 持续 {values.get('duration', '未明确')}\n"
        f"当前阶段：{STAGE_LABELS.get(stage, stage) or '—'}\n"
        f"本次表述：{text}"
    )


def _recent_messages(state: PreConsultState, n: int = 6) -> list[dict]:
    out: list[dict] = []
    for message in (state.get("messages") or [])[-n:]:
        role = "patient" if isinstance(message, HumanMessage) else "assistant"
        out.append({"role": role, "content": getattr(message, "content", "")})
    return out
