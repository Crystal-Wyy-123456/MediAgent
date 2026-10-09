"""Pipeline 编排：跨 Agent 数据只走 Orchestrator 的 current_context，Agent 之间互不知晓。

★ 踩过的坑：预问诊输出 `draft_record_id`，质控期望 `record_id` —— Pipeline 能跑通但
联动失效，排查很久。教训是「接缝处的契约必须显式化，不能靠约定」，于是有了这张映射表。
"""

from __future__ import annotations

from dataclasses import dataclass

from .schema import AgentType


@dataclass
class PipelineSpec:
    mode: str
    label: str
    agents: list[AgentType]
    description: str


PIPELINES: dict[str, PipelineSpec] = {
    "preconsult_review": PipelineSpec(
        mode="preconsult_review",
        label="预问诊 → 病历质控 全链路",
        agents=[AgentType.PRECONSULT, AgentType.MEDREVIEW],
        description="预问诊采集完成后生成病历草稿，经门控检查后送入三轨质控。",
    ),
}

# ★ 跨 Agent 字段映射表（解决「Agent 之间字段名不一致」的经典问题）
CONTEXT_MAPPING: dict[AgentType, list[tuple[str, str]]] = {
    AgentType.PRECONSULT: [
        ("draft_record_id", "draft_record_id"),
        ("chief_complaint", "chief_complaint"),
        ("completeness_score", "completeness_score"),
        ("draft_record", "draft_record"),
        ("handover", "handover"),
    ],
    AgentType.MEDREVIEW: [
        ("review_id", "record_review_id"),
        ("overall_score", "quality_score"),
    ],
}


@dataclass
class GateResult:
    abort: bool
    reason: str
    detail: str = ""


def gate_red_flag(context: dict, response: dict) -> GateResult | bool:
    """门控 1：命中红旗症状 → 中止，转医生接管。"""
    del context
    if response.get("handover"):
        return GateResult(abort=True, reason="RED_FLAG_HANDOVER", detail="预问诊命中红旗症状，已挂起流程转医生接管")
    return True


def gate_completeness(context: dict, response: dict) -> GateResult | bool:
    """门控 2：信息完整度 < 60 → 中止，转人工补录。"""
    del context
    score = response.get("completeness_score", 100)
    if score is not None and score < 60:
        return GateResult(
            abort=True, reason="INSUFFICIENT_INFO", detail=f"预问诊完整度 {score} 分（低于 60），需人工补录后再质控"
        )
    return True


PIPELINE_GATES: dict[str, list] = {
    "preconsult_review": [gate_red_flag, gate_completeness],
}


def pipeline_topology() -> list[dict]:
    return [
        {
            "mode": spec.mode,
            "label": spec.label,
            "description": spec.description,
            "agents": [a.value for a in spec.agents],
            "gates": ["RED_FLAG_HANDOVER（命中红旗症状即中止）", "INSUFFICIENT_INFO（完整度低于 60 即中止）"],
            "mapping": {a.value: [list(pair) for pair in pairs] for a, pairs in CONTEXT_MAPPING.items()},
        }
        for spec in PIPELINES.values()
    ]
