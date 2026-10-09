"""阶段判定是纯代码 —— 所以它 100% 可单测，这正是「不让 LLM 判断阶段」的价值。"""

from __future__ import annotations

from backend.agents.preconsult.stages import MIN_TURNS, evaluate_stage


def test_advance_requires_both_turns_and_slots():
    """轮数够但槽位没填满 → 不推进。"""
    outcome = evaluate_stage(
        "HISTORY",
        stage_turn_count=5,
        filled_slots={"HISTORY": ["onset"]},
        min_turns=MIN_TURNS,
    )
    assert outcome["advanced"] is False
    assert "symptoms" in outcome["missing_slots"]


def test_advance_when_slots_complete_but_turns_not_enough():
    """槽位齐备但轮数不足 → 依然不推进（两个条件必须同时满足）。"""
    outcome = evaluate_stage(
        "HISTORY",
        stage_turn_count=1,
        filled_slots={"HISTORY": ["onset", "symptoms", "aggravating_factors"]},
        min_turns=MIN_TURNS,
    )
    assert outcome["advanced"] is False
    assert outcome["slots_ok"] is True and outcome["turns_ok"] is False


def test_advance_to_next_stage():
    outcome = evaluate_stage(
        "HISTORY",
        stage_turn_count=3,
        filled_slots={"HISTORY": ["onset", "symptoms", "aggravating_factors"]},
        min_turns=MIN_TURNS,
    )
    assert outcome["advanced"] is True
    assert outcome["next_stage"] == "PAST_HISTORY"


def test_last_stage_finishes():
    outcome = evaluate_stage("SUMMARY", 1, {"SUMMARY": ["patient_ack"]}, min_turns=MIN_TURNS)
    assert outcome["next_stage"] == "FINISHED"


def test_unknown_stage_is_safe():
    outcome = evaluate_stage("NOPE", 9, {}, min_turns=MIN_TURNS)
    assert outcome["advanced"] is False
