"""MedReview 节点实现 —— 三轨并行 + 节点内 asyncio.gather。

为什么用 asyncio.gather 而不是 LangGraph 的 Send API：
三轨/六维度的数量是确定的，且都在同一个节点内完成。gather 代码更短、
调试更直观（打一个断点就能看到三轨的全部返回）。Send API 的价值在
「图级动态扇出 + 断点续跑」，这个场景用不上。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid

from ...infra.db import db
from ...infra.llm_factory import llm_factory
from ...observability.trace import span, traced
from .prompts import DIMENSION_PROMPTS, EXTRACT_PROMPT
from .rules import run_rule_track
from .state import DimensionResult, ExtractedRecord, ReviewState

llm = llm_factory.get("main")

REVIEW_DIMENSIONS = [
    "completeness",
    "consistency",
    "diagnosis_basis",
    "medication_rationality",
    "logic",
    "standardization",
]

DRUG_PATTERN = re.compile(
    r"(二甲双胍|阿司匹林|华法林|氨氯地平|头孢[\u4e00-\u9fa5]{0,4}|阿莫西林|左氧氟沙星|莫西沙星|阿奇霉素|哌拉西林|美托洛尔|胰岛素|呋塞米|布洛芬)"
)
LAB_PATTERN = re.compile(r"(血糖|HbA1c|糖化血红蛋白|肌酐|血钾|白细胞|WBC)\s*[：:]?\s*(\d+(?:\.\d+)?)")
LAB_ABNORMAL_UPPER = {"血糖": 6.1, "HbA1c": 6.5, "糖化血红蛋白": 6.5, "肌酐": 111}


@traced("node.parse", kind="node")
async def parse_node(state: ReviewState) -> dict:
    """文档解析：把上传的 PDF/DOCX/文本统一成纯文本。"""
    raw = (state.get("raw_document") or "").strip()
    if "手术记录" in raw:
        record_type = "surgery"
    elif "出院记录" in raw or "出院小结" in raw:
        record_type = "discharge"
    else:
        record_type = "admission"
    return {
        "raw_document": raw,
        "record_type": record_type,
        "review_id": state.get("review_id") or f"rev_{uuid.uuid4().hex[:12]}",
    }


@traced("node.extract", kind="node")
async def extract_node(state: ReviewState) -> dict:
    """结构化提取 —— Pydantic 强约束，产出直接进下游，不让下游解析自由文本。"""
    result = await llm.with_structured_output(ExtractedRecord, task="extract").ainvoke(
        EXTRACT_PROMPT.format(document=state["raw_document"]),
        payload={"raw_document": state["raw_document"]},
    )
    return {"structured_record": result.model_dump()}


async def _llm_track(record: dict, raw_text: str) -> list[dict]:
    """轨2：六维度并发评审（维度彼此正交、无依赖，串行跑是 6 倍耗时）。"""

    async def one(dimension: str) -> dict:
        async with span(f"dimension.{dimension}", kind="review", dimension=dimension):
            result = await llm.with_structured_output(DimensionResult, task="dimension").ainvoke(
                DIMENSION_PROMPTS[dimension].format(document=raw_text),
                payload={"dimension": dimension, "record": record},
            )
        return result.model_dump()

    return list(await asyncio.gather(*[one(dim) for dim in REVIEW_DIMENSIONS]))


def _drug_of(order: str) -> str | None:
    m = DRUG_PATTERN.search(order)
    return m.group(1) if m else None


def _abnormal_lab(lab: str) -> tuple[str, str] | None:
    m = LAB_PATTERN.search(lab)
    if not m:
        return None
    name, raw_value = m.group(1), m.group(2)
    value = float(raw_value)
    if name in LAB_ABNORMAL_UPPER and value > LAB_ABNORMAL_UPPER[name]:
        return name, raw_value
    if name == "血钾" and value < 3.5:
        return name, raw_value
    return None


def _cross_doc_track(record: dict, raw_text: str) -> list[dict]:
    """轨3：数据比对 —— 医嘱 ↔ 病程记录 ↔ 检验报告 三方一致性。

    本质是数据比对问题：先结构化提取再比对，比让 LLM 读全文更准。
    """
    results: list[dict] = []
    course_text = " ".join(record.get("course_notes") or []) or raw_text

    for i, order in enumerate(record.get("orders") or [], start=1):
        drug = _drug_of(order)
        if drug and drug not in course_text:
            results.append(
                {
                    "check_id": f"C{i:03d}",
                    "name": "医嘱 ↔ 病程记录一致性",
                    "consistent": False,
                    "a_source": "医嘱",
                    "a_value": order[:60],
                    "b_source": "病程记录",
                    "b_value": "未检索到对应记录",
                    "note": f"医嘱「{order[:40]}」在病程记录中未见执行或调整说明",
                }
            )

    for i, lab in enumerate(record.get("lab_results") or [], start=1):
        abnormal = _abnormal_lab(lab)
        if abnormal and abnormal[0] not in course_text:
            results.append(
                {
                    "check_id": f"L{i:03d}",
                    "name": "检验结果 ↔ 病程记录分析",
                    "consistent": False,
                    "a_source": "辅助检查",
                    "a_value": lab[:60],
                    "b_source": "病程记录",
                    "b_value": "未见对该结果的临床意义分析",
                    "note": f"{abnormal[0]} 异常（{abnormal[1]}）但病程记录中未分析并记录处理措施",
                }
            )
    return results


@traced("node.run_three_tracks", kind="node")
async def run_three_tracks_node(state: ReviewState) -> dict:
    """三轨并行：规则引擎轨 + LLM 评审轨 + 数据比对轨。"""
    record = state["structured_record"]
    raw_text = state["raw_document"]

    async def rule_track() -> list[dict]:
        async with span("track.rule_engine", kind="track", engine="rule"):
            return run_rule_track(record, raw_text)

    async def llm_track() -> list[dict]:
        async with span("track.llm_review", kind="track", engine="llm"):
            return await _llm_track(record, raw_text)

    async def cross_track() -> list[dict]:
        async with span("track.cross_doc", kind="track", engine="compare"):
            return _cross_doc_track(record, raw_text)

    rule_results, dimension_results, cross_doc_results = await asyncio.gather(
        rule_track(), llm_track(), cross_track()
    )
    return {
        "rule_results": rule_results,
        "dimension_results": dimension_results,
        "cross_doc_results": cross_doc_results,
    }


def compute_weighted_score(rules: list[dict], dimensions: list[dict], cross: list[dict]) -> float:
    """加权综合评分：规则 30% + LLM 维度 55% + 跨文档比对 15%（满分 10）。"""
    total_weight = sum(r.get("weight", 1.0) for r in rules) or 1.0
    passed_weight = sum(r.get("weight", 1.0) for r in rules if r.get("passed"))
    rule_score = 10.0 * passed_weight / total_weight
    dim_score = sum(d.get("score", 0.0) for d in dimensions) / max(1, len(dimensions))
    cross_score = max(0.0, 10.0 - 1.8 * len(cross))
    return round(0.30 * rule_score + 0.55 * dim_score + 0.15 * cross_score, 2)


def grade_of(score: float) -> str:
    if score >= 9.0:
        return "甲级（优秀）"
    if score >= 8.0:
        return "乙级（良好）"
    if score >= 7.0:
        return "丙级（合格）"
    return "丁级（需整改）"


@traced("node.aggregate", kind="node")
async def aggregate_node(state: ReviewState) -> dict:
    """Fan-in 汇总：三轨产出结构完全不同，必须统一成 IssueItem 供前端渲染。"""
    issues: list[dict] = []

    for r in state.get("rule_results", []):
        if r.get("passed"):
            continue
        issues.append(
            {
                "issue_id": r["rule_id"],
                "dimension": "rule",
                "severity": r["level"],
                "title": r["rule_name"],
                "evidence": r.get("evidence", ""),
                "location": r.get("location", ""),
                "suggestion": r.get("suggestion", ""),
                "source_rule": r["rule_id"],
            }
        )

    for dim in state.get("dimension_results", []):
        for item in dim.get("issues", []):
            issues.append(item)

    for c in state.get("cross_doc_results", []):
        if c.get("consistent"):
            continue
        issues.append(
            {
                "issue_id": c["check_id"],
                "dimension": "cross_doc",
                "severity": "warn",
                "title": c["name"],
                "evidence": f"{c['a_source']}：{c['a_value']}｜{c['b_source']}：{c['b_value']}",
                "location": f"{c['a_source']} / {c['b_source']}",
                "suggestion": c.get("note", ""),
                "source_rule": c["check_id"],
            }
        )

    score = compute_weighted_score(
        state.get("rule_results", []), state.get("dimension_results", []), state.get("cross_doc_results", [])
    )
    severity_order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda i: severity_order.get(i.get("severity", "info"), 3))
    for issue in issues:
        issue["accepted"] = None

    return {
        "issues": issues,
        "overall_score": score,
        "grade": grade_of(score),
        "report": {
            "review_id": state.get("review_id"),
            "overall_score": score,
            "grade": grade_of(score),
            "issue_count": len(issues),
            "severity_count": {
                "error": sum(1 for i in issues if i["severity"] == "error"),
                "warn": sum(1 for i in issues if i["severity"] == "warn"),
                "info": sum(1 for i in issues if i["severity"] == "info"),
            },
            "dimension_scores": {d["dimension"]: d["score"] for d in state.get("dimension_results", [])},
            "track_summary": {
                "rule": {
                    "total": len(state.get("rule_results", [])),
                    "passed": sum(1 for r in state.get("rule_results", []) if r.get("passed")),
                    "tokens": 0,
                },
                "llm": {"dimensions": len(state.get("dimension_results", [])), "engine": "llm"},
                "cross_doc": {
                    "total": len(state.get("cross_doc_results", [])),
                    "inconsistent": sum(1 for c in state.get("cross_doc_results", []) if not c.get("consistent")),
                },
            },
            "rule_pass_rate": round(
                sum(1 for r in state.get("rule_results", []) if r["passed"]) / max(1, len(state.get("rule_results", []))), 4
            ),
        },
    }


@traced("node.persist", kind="node")
async def persist_node(state: ReviewState) -> dict:
    """持久化到 PostgreSQL（本地部署用 SQLite 同构），半结构化结果以 JSONB 存放。"""
    review_id = state.get("review_id") or f"rev_{uuid.uuid4().hex[:12]}"
    record = state.get("structured_record", {})
    report = state.get("report", {})
    await db.execute(
        """INSERT OR REPLACE INTO record_review
           (review_id, tenant_id, patient_name, structured_record, dimension_results, rule_results,
            cross_doc_results, overall_score, grade, status, elapsed_ms, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            review_id,
            state.get("tenant_id", ""),
            record.get("patient_name", ""),
            json.dumps(record, ensure_ascii=False),
            json.dumps(state.get("dimension_results", []), ensure_ascii=False),
            json.dumps(state.get("rule_results", []), ensure_ascii=False),
            json.dumps(state.get("cross_doc_results", []), ensure_ascii=False),
            report.get("overall_score"),
            report.get("grade"),
            "completed",
            state.get("elapsed_ms"),
            time.time(),
        ),
    )
    for issue in state.get("issues", []):
        await db.execute(
            """INSERT OR REPLACE INTO review_issue
               (issue_id, review_id, dimension, severity, title, evidence, location, suggestion, source_rule, accepted, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"{review_id}:{issue['issue_id']}",
                review_id,
                issue["dimension"],
                issue["severity"],
                issue["title"],
                issue.get("evidence", ""),
                issue.get("location", ""),
                issue.get("suggestion", ""),
                issue.get("source_rule"),
                None,
                time.time(),
            ),
        )
    return {"review_id": review_id}
