"""PreConsult 的 State —— 22 个字段跨轮持久化，由 Checkpointer 自动管理。"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class AnswerQuality(BaseModel):
    """回答质量四档标签 —— 这一步必须用 LLM，因为需要语义理解。"""

    grade: Literal["EXCELLENT", "ADEQUATE", "WEAK", "NO_ANSWER"] = "ADEQUATE"
    extracted_slots: dict = Field(default_factory=dict)
    reason: str = ""


class RedFlagJudgement(BaseModel):
    """红旗症状的二次兜底判断（规则未命中时才会调用）。"""

    hit: bool = False
    flags: list[str] = Field(default_factory=list)
    reason: str = ""


class PatientRecord(BaseModel):
    """预问诊产出的病历草稿 —— 下游 MedReview 的输入契约。"""

    draft_record_id: str
    patient_name: str = ""
    gender: str = ""
    age: str = ""
    chief_complaint: str = ""
    history_of_present_illness: str = ""
    past_history: str = ""
    medication_history: str = ""
    allergy_history: str = ""
    completeness_score: float = 0.0
    handover: bool = False


class PreConsultState(TypedDict, total=False):
    # ── 对话 ──
    messages: Annotated[list, add_messages]
    patient_message: str

    # ── 阶段状态（5 个）──
    current_stage: str
    stage_turn_count: int
    filled_slots: dict
    slot_values: dict
    current_question: str
    followup_count: int

    # ── 质量与风险（4 个）──
    last_answer_quality: str
    rephrase_count: int
    handover: bool
    handover_reason: list
    handover_note: str
    red_flag_alert: dict
    doctor_id: str

    # ── 采集结果（5 个）──
    chief_complaint: str
    history_of_present_illness: str
    past_history: str
    medication_history: str
    allergy_history: str

    # ── 会话与隔离（4 个）──
    session_id: str
    tenant_id: str
    patient_id: str
    summary: str

    # ── 产出（4 个）──
    draft_record: dict
    report: dict
    started_at: str
    turn_count: int
    last_route: str
    stage_decision: dict
    compressed: bool
