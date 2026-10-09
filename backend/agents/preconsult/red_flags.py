"""红旗症状规则表 —— 命中即挂起流程转医生接管。

三层保险，宁可多提醒，不可漏：
  1) 关键词组合：每条规则由若干「同义词组」组成 —— 组内命中任一说法、组间需全部命中。
     口语化说法（喘不过气 / 上不来气 / 憋得慌 / 疼得受不了…）都做了覆盖。
  2) 否定识别：「没有胸痛」「无大汗」「否认咯血」不算命中，避免误报打断问诊。
     否定只在同一小句内生效，跨逗号/句号不再传递（「没精神，胸闷」不会被误判成否定胸闷）。
  3) 语义兜底：规则未命中但出现预警症状时，再补一次语义判断（见 preconsult/nodes.py）。

跨轮次同样生效：患者分两轮分别说出的症状，合并后一起判断（见节点里的 _recent_patient_text）。
"""

from __future__ import annotations

RED_FLAGS: dict[str, dict] = {
    # ── 循环 / 呼吸：一旦命中立即转医生 ──
    "chest_pain_with_diaphoresis": {
        "label": "胸痛伴大汗（急性冠脉综合征高危）",
        "keywords": [
            ["胸痛", "胸口痛", "胸口疼", "心前区疼痛", "胸骨后疼痛", "压榨性疼痛", "胸口压榨感"],
            ["大汗", "冷汗", "冒汗", "汗湿", "浑身是汗", "大汗淋漓"],
        ],
        "advice": "立即启动胸痛中心流程，10 分钟内完成心电图并检测肌钙蛋白。",
        "severity": "critical",
    },
    "severe_dyspnea": {
        "label": "呼吸困难（气促 / 憋喘）",
        "keywords": [[
            "呼吸困难", "喘不过气", "喘不过气来", "喘不上气", "喘不上来", "上不来气", "吸不上气",
            "透不过气", "无法呼吸", "憋气", "憋得慌", "憋喘", "喘憋", "喘得厉害", "喘息",
            "端坐呼吸", "气促", "呼吸急促", "呼吸费力",
        ]],
        "advice": "立即评估血氧饱和度与呼吸频率，必要时给氧并转入抢救区。",
        "severity": "critical",
    },
    "consciousness_disorder": {
        "label": "意识障碍（晕厥 / 昏迷）",
        "keywords": [[
            "意识模糊", "意识不清", "意识丧失", "昏迷", "晕厥", "晕倒", "不省人事",
            "叫不醒", "差点晕过去", "眼前发黑要倒",
        ]],
        "advice": "立即评估生命体征、血糖与神经系统体征，警惕脑血管事件。",
        "severity": "critical",
    },
    "stroke_signs": {
        "label": "疑似脑卒中（肢体无力 / 言语不清）",
        "keywords": [[
            "偏瘫", "半身无力", "一侧无力", "手脚无力", "肢体无力", "一边使不上劲",
            "口角歪斜", "嘴歪", "说话不清", "吐字不清", "言语不清", "一侧麻木", "半边麻木",
        ]],
        "advice": "立即启动卒中绿色通道，确认发病时间并安排头颅影像检查。",
        "severity": "critical",
    },
    "seizure": {
        "label": "抽搐 / 惊厥发作",
        "keywords": [["抽搐", "抽风", "四肢抽动", "口吐白沫", "惊厥", "抽过去了"]],
        "advice": "保护气道与肢体，记录发作时长，评估有无外伤与持续状态。",
        "severity": "critical",
    },
    "severe_bleeding": {
        "label": "呕血 / 咯血 / 便血",
        "keywords": [[
            "呕血", "咯血", "咳血", "吐血", "咯鲜血", "呕吐咖啡样物",
            "便血", "鲜血便", "黑便", "大便发黑", "柏油样便", "大出血", "血尿",
        ]],
        "advice": "评估出血量与生命体征，建立静脉通路并启动相应绿色通道。",
        "severity": "critical",
    },
    "anaphylaxis": {
        "label": "严重过敏反应（皮疹伴呼吸困难）",
        "keywords": [
            ["皮疹", "风团", "荨麻疹", "面唇肿胀", "眼睑肿胀", "喉咙发紧", "喉头发紧", "全身发痒"],
            ["呼吸困难", "喘不过气", "喘不上气", "憋气", "嗓子发紧", "吞咽困难"],
        ],
        "advice": "立即评估气道与循环，按严重过敏反应处理并准备抢救用药。",
        "severity": "critical",
    },
    # ── 需要尽快排查（高危，未必立即抢救）──
    "chest_pain": {
        "label": "胸痛待排查",
        "keywords": [["胸痛", "胸口痛", "胸口疼", "心前区疼痛", "胸骨后疼痛", "压榨性疼痛", "胸口压榨感"]],
        "advice": "尽快完成心电图与心肌损伤标志物检查，排查急性冠脉综合征。",
        "severity": "high",
    },
    "chest_tightness_unrelieved": {
        "label": "胸闷持续不缓解",
        "keywords": [
            ["胸闷", "胸口发闷", "胸口压迫感", "胸口堵得慌"],
            ["不缓解", "持续不缓解", "一直不缓解", "没有缓解", "不见好转", "越来越重", "逐渐加重", "持续加重", "一阵比一阵重"],
        ],
        "advice": "尽快完成心电图与心肌损伤标志物检查，评估是否为急性冠脉综合征。",
        "severity": "high",
    },
    "severe_abdominal_pain": {
        "label": "剧烈腹痛",
        "keywords": [
            ["腹痛", "肚子疼", "肚子痛", "腹部疼痛", "上腹痛", "下腹痛"],
            ["剧烈", "剧痛", "绞痛", "疼得受不了", "痛得受不了", "疼得直不起腰", "难以忍受"],
        ],
        "advice": "评估有无腹膜刺激征与出血征象，完善腹部影像与血常规检查。",
        "severity": "high",
    },
    "high_fever_with_rash": {
        "label": "高热伴皮疹",
        "keywords": [["高热", "持续发热", "高烧"], ["皮疹", "全身皮疹", "出血点", "皮下出血"]],
        "advice": "警惕严重感染或药物超敏反应，评估有无黏膜受累。",
        "severity": "high",
    },
}

# 出现这些症状时，即使规则未命中也要再补一次语义判断
WARNING_SYMPTOMS = [
    "胸痛", "胸闷", "心悸", "心慌", "气短", "气促", "呼吸困难", "喘不过气", "喘不上气", "憋气",
    "头晕", "头痛", "出汗", "冷汗", "黑便", "便血", "发热", "腹痛", "呕吐", "乏力", "麻木", "无力",
]

# 否定词：出现在症状词之前，说明患者是在排除该症状
NEGATIONS = ("没有", "没", "无", "未", "否认", "并非", "不是", "排除", "不伴", "不觉得")

# 否定只在同一小句内生效；顿号属于并列项，不切断否定
CLAUSE_BREAKS = "，,。；;！!？?\n（）()：:"
NEGATION_WINDOW = 8      # 长句里只看症状词前 8 个字
MAX_NEGATION_SPAN = 24   # 短句/并列项允许回溯到小句开头


def _prefix(text: str, idx: int) -> str:
    """取症状词之前的同一小句片段，用于判断是否被否定。

    · 「没精神，胸痛」——逗号切断，胸痛不会被前面的「没」否定
    · 「否认咯血、呕血」——顿号是并列项，同一句里的否定对两者都生效
    """
    head = text[:idx]
    cut = max((head.rfind(ch) for ch in CLAUSE_BREAKS), default=-1)
    clause = head[cut + 1 :]
    return clause if len(clause) <= MAX_NEGATION_SPAN else clause[-NEGATION_WINDOW:]


def mentions(text: str, word: str) -> bool:
    """带否定检测的匹配：『没有胸痛』『无大汗』不算命中。"""
    start = 0
    while True:
        idx = text.find(word, start)
        if idx < 0:
            return False
        if not any(neg in _prefix(text, idx) for neg in NEGATIONS):
            return True
        start = idx + 1


def detect_red_flags(text: str) -> list[dict]:
    """关键词组合匹配 —— 每组关键词至少要命中一个同义词，所有组都命中才算命中。

    注意每组内是**同义词**（「大汗 / 冷汗 / 冒汗」都要算），组间是**组合条件**。
    """
    hits: list[dict] = []
    for name, rule in RED_FLAGS.items():
        if all(any(mentions(text, word) for word in group) for group in rule["keywords"]):
            hits.append({"name": name, **rule})
    return hits


def needs_llm_double_check(text: str, hits: list[dict]) -> bool:
    """规则未命中、但出现预警症状时，再补一次语义判断。"""
    if hits:
        return False
    return any(mentions(text, s) for s in WARNING_SYMPTOMS)
