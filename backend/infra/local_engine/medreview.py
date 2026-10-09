"""病历质控的语义侧实现 —— 结构化提取 + 六维度评审。

真实环境下这两步都是 LLM 调用；此处复刻的是**输出契约与判据**：
  1) extract_record      ：把自由文本病历抽成结构化字段
  2) dimension_result    ：对给定维度做语义评审并输出可审计的问题条目
"""

from __future__ import annotations

import re
import zlib

SECTION_ALIASES = {
    "主诉": "chief_complaint",
    "现病史": "present_illness",
    "既往史": "past_history",
    "过敏史": "allergy_history",
    "体格检查": "physical_exam",
    "查体": "physical_exam",
    "辅助检查": "auxiliary_exam",
    "初步诊断": "diagnosis",
    "入院诊断": "diagnosis",
    "诊断": "diagnosis",
    "诊疗计划": "treatment_plan",
    "处理意见": "treatment_plan",
    "医嘱": "orders",
    "长期医嘱": "orders",
    "病程记录": "course_notes",
    "入院时间": "admit_time",
    "入院日期": "admit_time",
    "记录时间": "record_time",
    "科室": "department",
    "姓名": "patient_name",
    "性别": "gender",
    "年龄": "age",
    "医师签名": "doctor_sign",
    "医生签名": "doctor_sign",
    "住院医师签名": "resident_sign",
    "上级医师签名": "resident_sign",
}

_SECTION_NAMES = "|".join(SECTION_ALIASES.keys())
# 兼容两种写法：【主诉】正文 与 主诉：正文；并且允许标题出现在同一行的中间
# （病历里常见「【入院时间】…　【记录时间】…」这种并排写法）
HEADER_RE = re.compile(
    r"(?:[（(]?\s*[一二三四五六七八九十\d]{1,3}\s*[）)、.．]\s*)?"
    r"(?:【\s*(" + _SECTION_NAMES + r")\s*】\s*[：:]?"
    r"|(?:^|[\n\r\s　])(" + _SECTION_NAMES + r")\s*[：:])"
)

DATETIME_RE = re.compile(
    r"(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?\s*(\d{1,2})?\s*[:：时]?\s*(\d{1,2})?"
)

DRUG_RULES = [
    {
        "drug": "二甲双胍",
        "level": "error",
        "danger": ["肾功能不全", "肾功能衰竭", "eGFR<30", "eGFR 28", "肌酐升高", "CKD"],
        "advice": "中重度肾功能不全（eGFR<30）禁用二甲双胍，建议改用胰岛素或经肾排泄影响小的降糖方案，并在病程中记录换药理由。",
    },
    {
        "drug": "阿司匹林",
        "level": "warn",
        "danger": ["消化道出血", "活动性溃疡", "血小板减少", "凝血功能异常"],
        "advice": "存在消化道出血/溃疡风险，使用阿司匹林需评估出血风险，建议加用质子泵抑制剂并在病程中记录风险评估结论。",
    },
    {
        "drug": "头孢",
        "level": "warn",
        "danger": ["饮酒", "酒精", "过敏性休克"],
        "advice": "头孢类与酒精存在双硫仑样反应风险，需在病历中明确禁酒告知并有患方签字确认。",
    },
    {
        "drug": "华法林",
        "level": "error",
        "danger": ["INR未监测", "INR 5", "出血"],
        "advice": "华法林治疗窗窄，必须记录 INR 监测结果与剂量调整依据。",
    },
]

ABNORMAL_LAB_RE = re.compile(r"(血糖|空腹血糖|WBC|白细胞|HbA1c|糖化血红蛋白|肌酐|肌钙蛋白|D-二聚体|血钾)\s*[：:]?\s*(\d+(?:\.\d+)?)")
LAB_UPPER = {"血糖": 6.1, "空腹血糖": 6.1, "HbA1c": 6.5, "糖化血红蛋白": 6.5, "肌酐": 111, "D-二聚体": 0.5}
LAB_LOWER = {"血钾": 3.5}


def _split_sections(text: str) -> tuple[dict[str, str], list[str]]:
    matches = list(HEADER_RE.finditer(text or ""))
    sections: dict[str, str] = {}
    found: list[str] = []
    for i, m in enumerate(matches):
        label = m.group(1) or m.group(2)
        key = SECTION_ALIASES[label]
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end() : end].strip(" \t\r\n-—")
        if key in sections and sections[key]:
            sections[key] += "；" + body
        else:
            sections[key] = body
        if label not in found:
            found.append(label)
    return sections, found


def _parse_time(value: str) -> str | None:
    m = DATETIME_RE.search(value or "")
    if not m:
        return None
    y, mo, d, hh, mm = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {int(hh or 0):02d}:{int(mm or 0):02d}"


def _lines(value: str) -> list[str]:
    out = []
    for raw in re.split(r"[\n;；]|(?<=。)\s*", value or ""):
        item = raw.strip(" -—•·\t")
        if len(item) >= 2:
            out.append(item)
    return out


def extract_record(payload: dict) -> dict:
    text = payload.get("raw_document", "") or ""
    sections, found = _split_sections(text)

    diagnosis_raw = sections.get("diagnosis", "")
    diagnosis = re.split(r"[；;、,，\n]", diagnosis_raw)
    diagnosis = [d.strip("。 　") for d in diagnosis if len(d.strip()) >= 2][:6]

    record_type = "surgery" if "手术记录" in text else "admission"
    if "出院记录" in text or "出院小结" in text:
        record_type = "discharge"

    return {
        "patient_name": (sections.get("patient_name") or "").split()[0] if sections.get("patient_name") else "",
        "gender": (sections.get("gender") or "").strip()[:2],
        "age": (sections.get("age") or "").strip()[:8],
        "department": (sections.get("department") or "").strip()[:20],
        "record_type": record_type,
        "admit_time": _parse_time(sections.get("admit_time", "")),
        "record_time": _parse_time(sections.get("record_time", "")),
        "chief_complaint": sections.get("chief_complaint", "").strip(),
        "present_illness": sections.get("present_illness", "").strip(),
        "past_history": sections.get("past_history", "").strip(),
        "allergy_history": sections.get("allergy_history", "").strip(),
        "physical_exam": sections.get("physical_exam", "").strip(),
        "auxiliary_exam": sections.get("auxiliary_exam", "").strip(),
        "diagnosis": diagnosis,
        "treatment_plan": sections.get("treatment_plan", "").strip(),
        "orders": _lines(sections.get("orders", "")),
        "course_notes": _lines(sections.get("course_notes", "")),
        "lab_results": _lines(sections.get("auxiliary_exam", "")),
        "doctor_sign": sections.get("doctor_sign", "").strip()[:32],
        "resident_sign": sections.get("resident_sign", "").strip()[:32],
        "sections_found": found,
        "word_count": len(re.sub(r"\s", "", text)),
    }


# ══════════════════════════════════════════════════════════════════
# 六维度语义评审
# ══════════════════════════════════════════════════════════════════
REQUIRED_SECTIONS = [
    ("chief_complaint", "主诉"),
    ("present_illness", "现病史"),
    ("past_history", "既往史"),
    ("allergy_history", "过敏史"),
    ("physical_exam", "体格检查"),
    ("auxiliary_exam", "辅助检查"),
    ("diagnosis", "初步诊断"),
    ("treatment_plan", "诊疗计划"),
]


def _issue(record: dict, dimension: str, severity: str, title: str, evidence: str, location: str, suggestion: str) -> dict:
    slug = re.sub(r"\W+", "", title)[:14]
    stable_id = zlib.crc32(title.encode("utf-8")) % 10000
    return {
        "issue_id": f"IS-{dimension[:4].upper()}-{stable_id:04d}",
        "dimension": dimension,
        "severity": severity,
        "title": f"{title}（{slug}）",
        "evidence": evidence[:220] if evidence else "（未见相关记录）",
        "location": location,
        "suggestion": suggestion,
        "source_rule": None,
    }


def _d_completeness(record: dict) -> tuple[float, list[dict], str]:
    issues: list[dict] = []
    for key, label in REQUIRED_SECTIONS:
        value = record.get(key)
        filled = bool(value) if isinstance(value, str) else bool(value)
        if not filled:
            issues.append(
                _issue(
                    record, "completeness", "error" if key in {"chief_complaint", "present_illness", "diagnosis"} else "warn",
                    f"缺少「{label}」记录", "", f"病历结构/{label}",
                    f"补充{label}，{label}是病历内涵质量的基础要素，缺失将直接影响诊断依据链完整性。",
                )
            )
    ill = record.get("present_illness", "")
    if ill and len(ill) < 60:
        issues.append(
            _issue(record, "completeness", "warn", "现病史要素不足", ill, "现病史",
                   "现病史应按「起病时间+诱因+症状特点+演变过程+诊疗经过+一般情况」六要素书写。"),
        )
    score = max(3.0, 10.0 - 1.1 * len(issues))
    return round(score, 1), issues, f"病历要素 {len(REQUIRED_SECTIONS)} 项逐项检查，发现 {len(issues)} 项缺失/不足"


def _d_consistency(record: dict) -> tuple[float, list[dict], str]:
    issues: list[dict] = []
    text = " ".join(str(v) for v in record.values() if isinstance(v, str))
    for dx in record.get("diagnosis", []):
        core = re.sub(r"[（(].*?[)）]", "", dx).strip()
        core = re.split(r"[，,、 ]", core)[0]
        # 用疾病名前缀做匹配：诊断常带分级/危险度（如「高血压3级 很高危」），
        # 不能拿全串去比对，否则全是误报
        disease = core[:3]
        if len(disease) >= 2 and disease not in text:
            issues.append(
                _issue(record, "consistency", "warn", f"诊断「{dx}」与病史/检查表述不一致", dx, "初步诊断",
                       f"「{dx}」在现病史与辅助检查中缺少对应表述，建议在病史或检查结果中补充支撑描述，避免诊断与记录脱节。"),
            )

    cc = record.get("chief_complaint", "")
    ill = record.get("present_illness", "")
    cc_time = re.search(r"(\d+)\s*(天|周|月|年|小时)", cc)
    ill_time = re.search(r"(\d+)\s*(天|周|月|年|小时)", ill)
    if cc_time and ill_time and cc_time.group(0) != ill_time.group(0):
        issues.append(
            _issue(record, "consistency", "error", "主诉时长与现病史描述不一致",
                   f"主诉「{cc}」 vs 现病史「{ill[:60]}」", "主诉 / 现病史",
                   f"主诉记载 {cc_time.group(0)}，现病史记载 {ill_time.group(0)}，需核实并统一病程时长。"),
        )

    if record.get("past_history") and "过敏" not in record.get("allergy_history", "") and not record.get("allergy_history"):
        issues.append(
            _issue(record, "consistency", "warn", "既往史与过敏史信息未对齐", record.get("past_history", ""), "既往史",
                   "既往史中提及治疗史，但过敏史空缺，建议向患者核实后补记。"),
        )
    score = max(4.0, 10.0 - 1.3 * len(issues))
    return round(score, 1), issues, "主诉/诊断/病史三方交叉核对"


def _d_diagnosis_basis(record: dict) -> tuple[float, list[dict], str]:
    issues: list[dict] = []
    aux = record.get("auxiliary_exam", "") or ""
    extra_labs = record.get("lab_results", "")
    aux += extra_labs if isinstance(extra_labs, str) else " ".join(extra_labs or [])
    checks = [
        (["糖尿病"], ["血糖", "HbA1c", "糖化血红蛋白", "OGTT", "胰岛素"], "空腹血糖/糖化血红蛋白"),
        (["高血压"], ["血压", "动态血压", "心电图", "超声心动"], "血压监测或心电图"),
        (["肺炎", "感染"], ["CT", "胸片", "WBC", "白细胞", "CRP", "降钙素原"], "胸部影像或感染指标"),
        (["冠心病", "心梗", "心绞痛"], ["心电图", "肌钙蛋白", "冠脉", "CTA"], "心电图与心肌损伤标志物"),
        (["贫血"], ["血红蛋白", "血常规", "铁代谢"], "血常规及铁代谢"),
        (["肾功能", "肾衰"], ["肌酐", "尿素氮", "eGFR", "尿蛋白"], "肾功能与尿常规"),
    ]
    for dx_list, proof, need in checks:
        hit = [dx for dx in record.get("diagnosis", []) if any(k in dx for k in dx_list)]
        if hit and not any(p.lower() in aux.lower() for p in proof):
            issues.append(
                _issue(record, "diagnosis_basis", "error", f"诊断「{hit[0]}」缺少支撑检查",
                       f"初步诊断: {hit[0]}；辅助检查: {aux[:80] or '（空白）'}", "初步诊断 / 辅助检查",
                       f"建议补充{need}作为诊断依据，否则诊断依据链不完整（DRG/DIP 付费与病历内涵质量双重要求）。"),
            )
    if not any("鉴别" in str(x) for x in [record.get("treatment_plan", ""), record.get("physical_exam", "")]):
        issues.append(
            _issue(record, "diagnosis_basis", "info", "未见鉴别诊断记录", "", "初步诊断",
                   "建议在高风险主诉（如胸痛、发热待查）下补充鉴别诊断与排除依据。"),
        )
    score = max(4.0, 10.0 - 1.4 * len(issues))
    return round(score, 1), issues, f"诊断依据链核查 {len(checks)} 类常见诊断"


def _d_medication(record: dict) -> tuple[float, list[dict], str]:
    issues: list[dict] = []
    orders_text = "\n".join(record.get("orders", []))
    aux = record.get("auxiliary_exam", "") or ""
    extra_labs = record.get("lab_results", "")
    aux += extra_labs if isinstance(extra_labs, str) else " ".join(extra_labs or [])
    record_text = "\n".join([orders_text, record.get("past_history", ""), record.get("present_illness", ""), aux])

    # 肾功能相关的定量判断（关键词匹配只能覆盖显式表述，数值必须单独算）
    egfr = re.search(r"eGFR\s*[：:]?\s*(\d+(?:\.\d+)?)", aux + record_text, re.IGNORECASE)
    if "二甲双胍" in orders_text and egfr and float(egfr.group(1)) < 45:
        issues.append(
            _issue(record, "medication_rationality", "error", "二甲双胍用药风险未评估",
                   f"医嘱含二甲双胍，辅助检查示 eGFR {egfr.group(1)} ml/min/1.73m²（<45）", "医嘱 / 辅助检查",
                   "eGFR < 45 ml/min/1.73m² 禁用二甲双胍，建议立即停用并改用其他降糖方案，同时在病程记录中记录换药理由与肾功能随访计划。"),
        )

    for rule in DRUG_RULES:
        if rule["drug"] in orders_text or rule["drug"] in record.get("treatment_plan", ""):
            hit = [d for d in rule["danger"] if d in record_text]
            if hit:
                issues.append(
                    _issue(record, "medication_rationality", rule["level"], f"{rule['drug']}用药风险未评估",
                           f"医嘱: {rule['drug']}；病历中出现「{hit[0]}」", "医嘱 / 病程记录", rule["advice"]),
                )

    abx = [o for o in record.get("orders", []) if any(k in o for k in ["头孢", "阿莫西林", "左氧氟沙星", "莫西沙星", "阿奇霉素", "哌拉西林"])]
    infection_dx = any(any(k in dx for k in ["感染", "肺炎", "炎", "脓毒"]) for dx in record.get("diagnosis", []))
    if len(abx) >= 2 and not infection_dx:
        issues.append(
            _issue(record, "medication_rationality", "warn", "联合使用两种抗菌药物但无联合用药指征记录",
                   "；".join(abx[:2]), "医嘱", "建议在病程记录中补充联合用药指征与病原学依据，或改为单药治疗。"),
        )
    if abx and not infection_dx and not any(k in record_text for k in ["CRP", "降钙素原", "白细胞", "WBC"]):
        issues.append(
            _issue(record, "medication_rationality", "warn", "使用抗菌药物缺少感染证据",
                   "；".join(abx[:1]), "医嘱", "建议补充感染相关检验（血常规/CRP/降钙素原）或病原学检查作为用药依据。"),
        )
    score = max(5.0, 10.0 - 1.5 * len(issues))
    return round(score, 1), issues, f"医嘱共 {len(record.get('orders', []))} 条，逐条做用药合理性核对"


def _d_logic(record: dict) -> tuple[float, list[dict], str]:
    issues: list[dict] = []
    notes = record.get("course_notes", [])
    times = [_parse_time(n) for n in notes]
    times = [t for t in times if t]
    if len(times) >= 2 and times != sorted(times):
        issues.append(
            _issue(record, "logic", "error", "病程记录时间顺序倒置", " > ".join(times[:3]), "病程记录",
                   "病程记录必须按时间先后书写，时间倒置属于病案首页与病历质量双重缺陷项。"),
        )
    if len(times) >= 2:
        d0 = _days_between(times[0], times[-1])
        if d0 and d0 > 3 and len(notes) < 2:
            issues.append(
                _issue(record, "logic", "warn", "病程记录频次不足", f"住院 {d0} 天，病程记录仅 {len(notes)} 条", "病程记录",
                       "按规范一般患者至少每 3 天记录一次病程，危重患者应每日记录。"),
            )
    plan = record.get("treatment_plan", "")
    if plan and record.get("present_illness") and len(plan) < 20:
        issues.append(
            _issue(record, "logic", "warn", "诊疗计划过于笼统，与病情演变无法对应", plan, "诊疗计划",
                   "诊疗计划应与现病史提出的问题逐条对应，便于后续病程记录体现执行与调整过程。"),
        )
    score = max(5.0, 10.0 - 1.3 * len(issues))
    return round(score, 1), issues, f"核查 {len(notes)} 条病程记录的时序与频次"


def _d_standardization(record: dict) -> tuple[float, list[dict], str]:
    issues: list[dict] = []
    text = " ".join(str(v) for v in record.values() if isinstance(v, str))
    abbreviations = {"FBS": "空腹血糖", "BP": "血压", "NS": "生理盐水", "GS": "葡萄糖注射液", "T": "体温"}
    for abbr, full in abbreviations.items():
        if re.search(rf"(?<![A-Za-z]){re.escape(abbr)}(?![A-Za-z])", text):
            issues.append(
                _issue(record, "standardization", "info", f"使用非规范缩写「{abbr}」", abbr, "病历全文",
                       f"病历书写规范要求使用规范中文名称，建议改为「{full}」。"),
            )
    cc = record.get("chief_complaint", "")
    if cc and not re.search(r"\d+\s*(天|周|月|年|小时|分钟)", cc):
        issues.append(
            _issue(record, "standardization", "warn", "主诉未按「症状+时长」规范书写", cc, "主诉",
                   "主诉应精炼为「主要症状 + 持续时间」，例如「反复胸闷 3 天」。"),
        )
    score = max(5.0, 10.0 - 1.0 * len(issues))
    return round(score, 1), issues, "术语与书写规范检查"


DIMENSIONS = {
    "completeness": _d_completeness,
    "consistency": _d_consistency,
    "diagnosis_basis": _d_diagnosis_basis,
    "medication_rationality": _d_medication,
    "logic": _d_logic,
    "standardization": _d_standardization,
}


def _days_between(a: str, b: str) -> int | None:
    import datetime as dt

    try:
        da = dt.datetime.strptime(a, "%Y-%m-%d %H:%M")
        db = dt.datetime.strptime(b, "%Y-%m-%d %H:%M")
        return abs((db - da).days)
    except Exception:  # noqa: BLE001
        return None


def dimension_result(payload: dict) -> dict:
    dimension = payload.get("dimension", "completeness")
    record = payload.get("record", {}) or {}
    fn = DIMENSIONS.get(dimension, _d_completeness)
    score, issues, summary = fn(record)
    return {
        "dimension": dimension,
        "score": score,
        "issues": issues,
        "summary": summary,
        "engine": "llm",
    }
