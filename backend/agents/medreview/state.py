"""MedReview 的 State 与结构化契约。"""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class ExtractedRecord(BaseModel):
    """结构化提取结果 —— Pydantic 强约束，避免让下游解析自由文本。"""

    patient_name: str = ""
    gender: str = ""
    age: str = ""
    department: str = ""
    record_type: str = "admission"
    admit_time: str | None = None
    record_time: str | None = None
    chief_complaint: str = ""
    present_illness: str = ""
    past_history: str = ""
    allergy_history: str = ""
    physical_exam: str = ""
    auxiliary_exam: str = ""
    diagnosis: list[str] = Field(default_factory=list)
    treatment_plan: str = ""
    orders: list[str] = Field(default_factory=list)
    course_notes: list[str] = Field(default_factory=list)
    lab_results: list[str] = Field(default_factory=list)
    doctor_sign: str = ""
    resident_sign: str = ""
    sections_found: list[str] = Field(default_factory=list)
    word_count: int = 0


class IssueItem(BaseModel):
    """质控问题清单 —— 三轨结果统一成同一种结构，前端才能统一渲染。"""

    issue_id: str
    dimension: str
    severity: Literal["error", "warn", "info"]
    title: str
    evidence: str = ""  # ★ 病历原文证据片段（可审计的关键）
    location: str = ""
    suggestion: str = ""
    source_rule: str | None = None
    accepted: bool | None = None


class DimensionResult(BaseModel):
    dimension: str
    score: float
    issues: list[IssueItem] = Field(default_factory=list)
    summary: str = ""
    engine: str = "llm"


class RuleCheckResult(BaseModel):
    rule_id: str
    rule_name: str
    passed: bool
    level: Literal["error", "warn", "info"] = "warn"
    weight: float = 1.0
    evidence: str = ""
    location: str = ""
    suggestion: str = ""


class CrossCheckResult(BaseModel):
    check_id: str
    name: str
    consistent: bool
    a_source: str
    a_value: str
    b_source: str
    b_value: str
    note: str = ""


class ReviewState(TypedDict, total=False):
    """节点内并发（本项目）不需要 Reducer；若改成图级并发，则六维度字段需写成
    `dimension_results: Annotated[list[dict], operator.add]` 由 LangGraph 自动 concat。"""

    raw_document: str
    structured_record: dict
    record_type: str

    rule_results: list[dict]
    dimension_results: list[dict]
    cross_doc_results: list[dict]

    overall_score: float
    grade: str
    issues: list[dict]
    report: dict

    tenant_id: str
    user_id: str
    review_id: str
    elapsed_ms: float
