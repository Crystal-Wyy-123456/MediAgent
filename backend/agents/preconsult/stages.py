"""阶段定义与推进条件 —— 阶段判定用纯代码：确定性、零 Token、100% 可单测。"""

from __future__ import annotations

STAGES = ["WARMUP", "CHIEF_COMPLAINT", "HISTORY", "PAST_HISTORY", "SUMMARY"]

MIN_TURNS = {
    "WARMUP": 1,
    "CHIEF_COMPLAINT": 2,
    "HISTORY": 3,
    "PAST_HISTORY": 2,
    "SUMMARY": 1,
}

# 宽松配置：最小轮数统一为 1，把「能不能推进」完全交给槽位完整性判定。
# 生产环境按租户加载不同配置（不同医院对问诊轮次的要求不同）。
RELAXED_MIN_TURNS = {stage: 1 for stage in STAGES}

# 槽位归属阶段：患者提前主动提供的信息，也能正确落到它所属的阶段
SLOT_OWNER = {
    "patient_confirmed": "WARMUP",
    "chief_complaint": "CHIEF_COMPLAINT",
    "duration": "CHIEF_COMPLAINT",
    "onset": "HISTORY",
    "symptoms": "HISTORY",
    "aggravating_factors": "HISTORY",
    "past_disease": "PAST_HISTORY",
    "medication": "PAST_HISTORY",
    "allergy": "PAST_HISTORY",
    "patient_ack": "SUMMARY",
}

REQUIRED_SLOTS = {
    "WARMUP": {"patient_confirmed"},
    "CHIEF_COMPLAINT": {"chief_complaint", "duration"},
    "HISTORY": {"onset", "symptoms", "aggravating_factors"},
    "PAST_HISTORY": {"past_disease", "medication"},
    "SUMMARY": {"patient_ack"},
}

STAGE_LABELS = {
    "WARMUP": "寒暄与身份确认",
    "CHIEF_COMPLAINT": "主诉与时长",
    "HISTORY": "现病史",
    "PAST_HISTORY": "既往史与用药史",
    "SUMMARY": "小结确认",
    "FINISHED": "已完成",
    "HANDOVER": "医生接管",
}

SLOT_LABELS = {
    "patient_confirmed": "身份确认",
    "chief_complaint": "主要症状",
    "duration": "持续时间",
    "onset": "起病时间",
    "symptoms": "症状特点",
    "aggravating_factors": "加重/缓解因素",
    "past_disease": "既往病史",
    "medication": "用药情况",
    "allergy": "过敏史",
    "patient_ack": "患者确认",
}


def active_min_turns() -> dict:
    from ...config import settings

    return RELAXED_MIN_TURNS if settings.preconsult_relaxed_turns else MIN_TURNS


def evaluate_stage(stage: str, stage_turn_count: int, filled_slots: dict, min_turns: dict | None = None) -> dict:
    """★ 纯代码阶段判定 —— 零 Token 消耗，100% 可单元测试。

    推进条件（两者同时满足）：
      1. 当前阶段轮数 >= 该阶段最小轮数
      2. 当前阶段必填槽位已全部填充
    """
    if stage not in STAGES:
        return {"advanced": False, "reason": f"阶段 {stage} 不在状态机中"}
    min_turns = min_turns or active_min_turns()
    turns_ok = stage_turn_count >= min_turns[stage]
    required = REQUIRED_SLOTS[stage]
    filled = set(filled_slots.get(stage, []))
    slots_ok = required.issubset(filled)
    missing = sorted(required - filled)
    if not (turns_ok and slots_ok):
        return {
            "advanced": False,
            "turns_ok": turns_ok,
            "slots_ok": slots_ok,
            "missing_slots": missing,
            "reason": f"轮数{'达标' if turns_ok else '不足'}（{stage_turn_count}/{min_turns[stage]}），槽位{'齐备' if slots_ok else '缺失 ' + '、'.join(missing)}",
        }
    idx = STAGES.index(stage)
    next_stage = STAGES[idx + 1] if idx + 1 < len(STAGES) else "FINISHED"
    return {"advanced": True, "next_stage": next_stage, "reason": "轮数与槽位双条件满足"}
