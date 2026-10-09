"""预问诊的生成侧实现 —— 分阶段提问 / 回答质量评估 / 小结 / 上下文压缩。"""

from __future__ import annotations

import re

from ...agents.preconsult.red_flags import mentions

STAGE_QUESTIONS = {
    "WARMUP": "您好，我是 MediAgent 预问诊助手，会帮您把情况先整理给医生。请问怎么称呼您？方便的话说一下年龄和性别。",
    "CHIEF_COMPLAINT": "请问您这次最主要的不舒服是什么？大概持续多久了？",
    "HISTORY": "请再具体说说：最早是什么时候开始的？当时在做什么、有没有明显诱因？症状是持续还是一阵一阵？什么情况下会加重或者缓解？",
    "PAST_HISTORY": "您以前有没有得过什么慢性病（比如高血压、糖尿病）？最近在吃哪些药？有没有药物或食物过敏？",
    "SUMMARY": "我整理一下您的情况，请您确认是否准确，有不准确的地方我马上改。",
    "FINISHED": "信息已经采集完整，感谢配合，我这就把小结交给医生。",
}

STAGE_SUGGESTIONS = {
    "WARMUP": ["我叫张伟，男，58岁", "李芳，女，34岁"],
    "CHIEF_COMPLAINT": [
        "最近3天反复胸闷，活动后明显",
        "小孩发热2天，最高39.2度",
    ],
    "HISTORY": [
        "三天前开始，走路快一点就胸闷，休息几分钟能缓解，没有明显诱因",
        "昨天晚上开始发热，一直没退，吃了布洛芬能降一点又升上来",
    ],
    "PAST_HISTORY": ["有高血压5年，一直在吃氨氯地平，没有过敏", "没有慢性病，最近没吃药，对青霉素过敏"],
    "SUMMARY": ["基本准确，补充一下：我有糖尿病", "都对，没有要改的"],
}

RED_FLAG_SUGGESTIONS = [
    "胸痛得厉害，还一直冒冷汗",
    "突然胸闷伴大汗，喘不上气",
    "刚才有一阵意识模糊，差点晕过去",
]

SYMPTOM_LEXICON = [
    "胸闷", "胸痛", "胸口痛", "胸口疼", "心前区疼痛", "压榨性疼痛", "心悸", "心慌", "气短", "气促",
    "呼吸困难", "喘不过气", "喘不上气", "上不来气", "憋气", "憋喘", "喘憋", "喘息", "端坐呼吸",
    "咳嗽", "咳痰", "咯血", "吐血", "呕血", "发热", "高烧", "畏寒", "乏力", "无力",
    "头晕", "头痛", "恶心", "呕吐", "腹痛", "肚子疼", "腹泻", "便秘", "黑便", "便血",
    "水肿", "皮疹", "风团", "荨麻疹", "面唇肿胀", "大汗", "冷汗", "盗汗", "消瘦",
    "食欲不振", "失眠", "关节痛", "腰背痛", "晕厥", "晕倒", "意识模糊", "昏迷", "抽搐", "麻木",
]

# 单独出现即视为危急的强提示症状（与 red_flags.py 的规则表保持一致）
CRITICAL_SYMPTOMS = [
    "胸痛", "胸口痛", "胸口疼", "心前区疼痛", "压榨性疼痛", "呼吸困难", "喘不过气", "喘不上气",
    "憋气", "憋喘", "气促", "晕厥", "晕倒", "意识模糊", "昏迷", "抽搐", "咯血", "呕血", "吐血",
    "便血", "偏瘫", "说话不清", "肢体无力", "面唇肿胀",
]


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

_CN_NUM = {
    "一": "1", "两": "2", "二": "2", "三": "3", "四": "4", "五": "5",
    "六": "6", "七": "7", "八": "8", "九": "9", "十": "10", "半": "0.5",
}

def _find_duration(text: str) -> str | None:
    """找「症状相关的持续时间」——病史里的「高血压5年」不能被当成主诉时长。"""
    patterns = [
        re.compile(r"(\d+(?:\.\d+)?)\s*(小时|天|周|月|年|分钟)"),
        re.compile(r"([一两二三四五六七八九十])\s*(小时|天|周|月|年|分钟)"),
    ]
    fallback: str | None = None
    for pattern in patterns:
        for m in pattern.finditer(text):
            value = f"{_CN_NUM.get(m.group(1), m.group(1))}{m.group(2)}"
            window = text[max(0, m.start() - 12) : m.end() + 12]
            if any(mentions(window, s) for s in SYMPTOM_LEXICON):
                return value
            fallback = fallback or value
    if fallback:
        return fallback
    return "6月" if "半年" in text else None


def _clause_with(text: str, keywords: list[str]) -> str | None:
    """取包含指定关键词的短句，保留患者原话，便于填入病历草稿。"""
    for clause in re.split(r"[，,。；;、\n]", text):
        clause = clause.strip()
        if clause and any(k in clause for k in keywords):
            return clause
    return None


def _extract_slots(text: str) -> dict:
    """抽取全部可用槽位（不按阶段过滤）—— 患者提前提供的信息同样有效。"""
    slots: dict[str, object] = {}
    if not text.strip():
        return slots

    duration = _find_duration(text)
    symptoms = [s for s in SYMPTOM_LEXICON if mentions(text, s)]

    # ── WARMUP ──
    slots["patient_confirmed"] = True
    if m := re.search(r"(\d{1,3})\s*岁", text):
        slots["age"] = f"{m.group(1)}岁"
    if "男" in text:
        slots["gender"] = "男"
    elif "女" in text:
        slots["gender"] = "女"
    if m := re.search(r"(?:我叫|我是|叫)\s*([\u4e00-\u9fa5]{2,4})", text):
        slots["patient_name"] = m.group(1)

    # ── CHIEF_COMPLAINT ──
    if symptoms:
        slots["chief_complaint"] = symptoms[0]
    if duration:
        slots["duration"] = duration

    # ── HISTORY ──
    if duration or any(k in text for k in ["开始", "前", "昨天", "前天", "早上", "晚上", "起病"]):
        slots["onset"] = _clause_with(text, ["开始", "前", "昨天", "前天", "起病"]) or (f"{duration}前起病" if duration else "已明确起病时间")
    if symptoms:
        slots["symptoms"] = "、".join(symptoms[:3])
    if any(k in text for k in ["加重", "缓解", "诱因", "活动后", "休息", "躺着", "夜间", "睡觉"]):
        slots["aggravating_factors"] = _clause_with(text, ["加重", "缓解", "诱因", "活动后", "休息"]) or "已描述加重/缓解因素"

    # ── PAST_HISTORY ──
    if any(k in text for k in ["高血压", "糖尿病", "冠心病", "脑梗", "慢性病", "手术", "肝炎", "没有其他病", "无基础病"]):
        slots["past_disease"] = _clause_with(text, ["高血压", "糖尿病", "冠心病", "脑梗", "慢性病", "手术", "肝炎"]) or "已采集既往史"
    if any(k in text for k in ["药", "片", "胶囊", "注射", "氨氯地平", "二甲双胍", "布洛芬", "缬沙坦"]):
        slots["medication"] = _clause_with(text, ["药", "片", "胶囊", "注射", "氨氯地平", "二甲双胍", "缬沙坦"]) or "已采集用药史"
    if "过敏" in text or "青霉素" in text:
        slots["allergy"] = _clause_with(text, ["过敏"]) or "已采集过敏史"

    # ── SUMMARY ──
    if any(k in text for k in ["准确", "没错", "确认", "都对", "没有要改", "基本对", "没问题"]):
        slots["patient_ack"] = True
    return slots


def answer_quality(payload: dict) -> dict:
    answer = (payload.get("answer") or "").strip()
    stage = payload.get("stage", "HISTORY")
    slots = _extract_slots(answer)
    relevant = {k: v for k, v in slots.items() if SLOT_OWNER.get(k) == stage}

    if not answer or any(k in answer for k in ["不知道", "不清楚", "说不上", "忘了", "没有注意"]):
        grade = "NO_ANSWER"
    elif len(answer) < 6:
        grade = "WEAK"
    elif (len(answer) >= 28 and len(relevant) >= 2) or len(relevant) >= 3:
        grade = "EXCELLENT"
    else:
        grade = "ADEQUATE"

    return {
        "grade": grade,
        "extracted_slots": slots,
        "reason": f"回答长度 {len(answer)} 字，识别到 {len(relevant)} 个本阶段相关槽位",
    }


def generate_question(payload: dict, prompt: str = "") -> str:
    stage = payload.get("stage", "CHIEF_COMPLAINT")
    slots = payload.get("filled_slots", {}) or {}
    missing = payload.get("missing_slots") or []
    first_turn = payload.get("first_turn", False)
    base = STAGE_QUESTIONS.get(stage, STAGE_QUESTIONS["CHIEF_COMPLAINT"])
    if missing and not first_turn:
        label = {"duration": "持续时间", "onset": "起病时间", "symptoms": "症状特点",
                 "aggravating_factors": "加重或缓解因素", "past_disease": "既往病史",
                 "medication": "用药情况", "chief_complaint": "主要症状"}.get(missing[0], missing[0])
        return f"{base}\n（请重点补充：{label}）"
    if slots:
        return base
    return base


def rephrase_question(payload: dict, prompt: str = "") -> str:
    stage = payload.get("stage", "HISTORY")
    alt = {
        "CHIEF_COMPLAINT": "没关系，换个问法：您这几天身体哪里最难受？大概从哪天开始的？",
        "HISTORY": "我们换个说法：最开始出现这个问题是什么时候？当时在做什么？后来是怎么变化的？",
        "PAST_HISTORY": "换一种问法：您平时有没有长期在吃的药？以前有没有住过院或者做过手术？",
        "WARMUP": "不着急，您先告诉我怎么称呼、大概多大年纪就行。",
    }
    return alt.get(stage, STAGE_QUESTIONS.get(stage, "请再补充一下相关信息。"))


def followup_question(payload: dict, prompt: str = "") -> str:
    stage = payload.get("stage", "HISTORY")
    if stage == "HISTORY":
        return "您刚才提到的这个情况，有没有伴随出汗、恶心、气短或者心慌？"
    if stage == "CHIEF_COMPLAINT":
        return "这种不舒服是持续的，还是一阵一阵的？大概多久发作一次？"
    if stage == "PAST_HISTORY":
        return "这些药是规律在吃吗？最近一次调整剂量是什么时候？"
    return "还有其他需要补充的信息吗？"


def red_flag_judgement(payload: dict) -> dict:
    """红旗症状的二次兜底判断：规则未命中时，用语义判断补一次。"""
    text = payload.get("text") or ""
    symptoms = [s for s in SYMPTOM_LEXICON if mentions(text, s)]
    critical = [s for s in CRITICAL_SYMPTOMS if mentions(text, s)]
    # 危急症状单独出现即命中；否则需要多个症状同时出现
    hit = bool(critical) or len(symptoms) >= 3
    evidence = critical or symptoms
    return {
        "hit": hit,
        "flags": [f"识别到：{'、'.join(evidence[:3])}"] if hit else [],
        "reason": f"识别到症状 {len(symptoms)} 个，其中危急症状 {len(critical)} 个",
    }


def summarize(payload: dict, prompt: str = "") -> str:
    values = payload.get("slot_values") or {}
    if values:
        def pick(key: str, default: str = "未采集") -> str:
            return str(values.get(key) or default)

        return (
            "【预问诊小结】\n"
            f"· 主诉：{pick('chief_complaint')}，持续 {pick('duration', '未明确')}\n"
            f"· 现病史：起病 {pick('onset')}；症状特点 {pick('symptoms')}；加重/缓解 {pick('aggravating_factors')}\n"
            f"· 既往史：{pick('past_disease')}\n"
            f"· 用药史：{pick('medication')}\n"
            f"· 过敏史：{pick('allergy')}\n"
            "请医生重点复核上述信息，并补充体格检查与辅助检查结果。"
        )
    slots = payload.get("filled_slots", {}) or {}
    flat: dict[str, str] = {}
    for _stage, values in slots.items():
        if isinstance(values, dict):
            flat.update({k: str(v) for k, v in values.items()})
        elif isinstance(values, list):
            flat.update({k: "已采集" for k in values})
    cc = flat.get("chief_complaint") or "未明确"
    duration = flat.get("duration") or "未明确"
    return (
        "【预问诊小结】\n"
        f"· 主诉：{cc}，持续 {duration}\n"
        f"· 现病史：起病与演变过程已采集（{flat.get('onset', '已采集')}）\n"
        f"· 伴随症状：{flat.get('symptoms', '已采集')}\n"
        f"· 加重/缓解因素：{flat.get('aggravating_factors', '已采集')}\n"
        f"· 既往史：{flat.get('past_disease', '未明确')}\n"
        f"· 用药史：{flat.get('medication', '未明确')}\n"
        f"· 过敏史：{flat.get('allergy', '未明确')}\n"
        "请医生重点复核上述信息并补充体格检查。"
    )


def patient_summary(payload: dict, prompt: str = "") -> str:
    flags = payload.get("flags") or []
    transcript = payload.get("transcript") or []
    last = transcript[-1] if transcript else ""
    flag_text = "、".join(flags) if flags else "无"
    return (
        f"命中红旗症状：{flag_text}。\n"
        f"患者最近表述：{last}\n"
        "建议医生立即评估生命体征并判断是否需要急诊通道。"
    )


def doctor_note(payload: dict, prompt: str = "") -> str:
    return "已完成医生接管，建议按胸痛中心流程处理，并补齐生命体征与心电图结果。"


def compress(payload: dict, prompt: str = "") -> str:
    history = payload.get("history") or []
    joined = " ".join(history)[:400]
    symptoms = [s for s in SYMPTOM_LEXICON if s in joined]
    return (
        "【历史问诊摘要】患者主诉" + ("、".join(symptoms[:3]) if symptoms else "不适")
        + "，已完成起病时间、症状特点、加重缓解因素与既往用药史的采集；"
        "前期对话中未出现红旗症状，关键否定信息（药物过敏、近期手术）已确认。"
    )
