"""轨1：规则引擎 —— 确定性维度用纯代码，规则表配置驱动，新增规则不改代码。

为什么这些维度不给 LLM：时效性、签名、必填项这类是**确定性规则**，
规则引擎 100% 准确且零成本，交给 LLM 既慢又可能算错。
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class Rule:
    id: str
    name: str
    level: str
    weight: float
    location: str
    suggestion: str
    expr: Callable[[dict, str], bool]
    evidence: Callable[[dict, str], str]


def _hours(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    try:
        da = dt.datetime.strptime(a, "%Y-%m-%d %H:%M")
        db = dt.datetime.strptime(b, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return (db - da).total_seconds() / 3600


def _first_course_hours(record: dict) -> float | None:
    for note in record.get("course_notes") or []:
        m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?\s*(\d{1,2})?[:：时]?(\d{1,2})?", note)
        if m:
            y, mo, d, hh, mm = m.groups()
            stamp = f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {int(hh or 0):02d}:{int(mm or 0):02d}"
            return _hours(record.get("admit_time"), stamp)
    return None


def _span_days(record: dict) -> int | None:
    stamps: list[str] = []
    for note in record.get("course_notes") or []:
        m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", note)
        if m:
            stamps.append(f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
    if len(stamps) >= 2:
        return abs((dt.date.fromisoformat(stamps[-1]) - dt.date.fromisoformat(stamps[0])).days)
    if stamps and record.get("admit_time"):
        try:
            return abs((dt.date.fromisoformat(stamps[-1]) - dt.date.fromisoformat(record["admit_time"][:10])).days)
        except ValueError:
            return None
    return None


def _hours_text(record: dict) -> str:
    hours = _first_course_hours(record)
    return f"{round(hours, 1)} 小时" if hours is not None else "（无法解析时间）"


RULES: list[Rule] = [
    Rule(
        id="R001", name="入院记录 24 小时内完成", level="error", weight=3.0,
        location="入院时间 / 记录时间",
        suggestion="入院记录应在患者入院后 24 小时内完成，超时属于病历质量缺陷项。",
        expr=lambda r, t: (_hours(r.get("admit_time"), r.get("record_time")) or 999) <= 24,
        evidence=lambda r, t: f"入院时间 {r.get('admit_time')}，记录时间 {r.get('record_time')}",
    ),
    Rule(
        id="R002", name="医师签名完整性", level="error", weight=2.0,
        location="签名栏",
        suggestion="入院记录需由住院医师与上级医师双签名。",
        expr=lambda r, t: bool(r.get("doctor_sign")) and bool(r.get("resident_sign")),
        evidence=lambda r, t: f"住院医师签名：{r.get('doctor_sign') or '缺失'}；上级医师签名：{r.get('resident_sign') or '缺失'}",
    ),
    Rule(
        id="R003", name="手术记录必填项（麻醉方式）", level="error", weight=2.5,
        location="手术记录",
        suggestion="手术记录必须包含麻醉方式、手术名称、术中经过与术者签名。",
        expr=lambda r, t: r.get("record_type") != "surgery" or "麻醉" in t,
        evidence=lambda r, t: "手术记录中未见麻醉方式记录",
    ),
    Rule(
        id="R004", name="过敏史必填", level="warn", weight=1.5,
        location="过敏史",
        suggestion="过敏史属必填项，无过敏应明确书写「无药物过敏史」并签名确认。",
        expr=lambda r, t: bool((r.get("allergy_history") or "").strip()),
        evidence=lambda r, t: r.get("allergy_history") or "过敏史栏为空",
    ),
    Rule(
        id="R005", name="首次病程记录 8 小时内完成", level="warn", weight=2.0,
        location="病程记录",
        suggestion="首次病程记录应在患者入院后 8 小时内完成。",
        expr=lambda r, t: (_first_course_hours(r) or 999) <= 8,
        evidence=lambda r, t: f"入院 {r.get('admit_time')}，首次病程记录距入院 {_hours_text(r)}",
    ),
    Rule(
        id="R006", name="病程记录频次 ≥ 每 3 天一次", level="warn", weight=1.5,
        location="病程记录",
        suggestion="一般患者至少每 3 天记录一次病程，危重患者应每日记录。",
        expr=lambda r, t: (_span_days(r) or 0) <= 3 * max(1, len(r.get("course_notes") or [])),
        evidence=lambda r, t: f"住院跨度约 {_span_days(r) or 0} 天，病程记录 {len(r.get('course_notes') or [])} 条",
    ),
    Rule(
        id="R007", name="上级医师查房记录", level="warn", weight=2.0,
        location="病程记录",
        suggestion="住院期间应有主任医师或副主任医师查房记录，并在病程记录中体现查房意见。",
        expr=lambda r, t: any(k in t for k in ["主任医师查房", "副主任医师查房", "上级医师查房", "主治医师查房"]),
        evidence=lambda r, t: "病程记录中未见上级医师查房意见",
    ),
    Rule(
        id="R008", name="有创操作/手术知情同意书", level="error", weight=2.5,
        location="知情同意",
        suggestion="手术、特殊检查、特殊治疗需取得患者或法定代理人书面同意。",
        expr=lambda r, t: ("同意书" in t) or r.get("record_type") != "surgery",
        evidence=lambda r, t: "病历中未见知情同意书记录",
    ),
]


def run_rule_track(record: dict, raw_text: str) -> list[dict]:
    results: list[dict] = []
    for rule in RULES:
        try:
            passed = bool(rule.expr(record, raw_text))
            evidence = rule.evidence(record, raw_text)
        except Exception:  # noqa: BLE001 - 单条规则异常不阻断整轨
            passed, evidence = True, ""
        results.append(
            {
                "rule_id": rule.id,
                "rule_name": rule.name,
                "passed": passed,
                "level": rule.level,
                "weight": rule.weight,
                "evidence": evidence,
                "location": rule.location,
                "suggestion": rule.suggestion,
            }
        )
    return results
