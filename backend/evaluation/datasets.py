"""离线标注集 —— 专家抽检样本（持续扩充至 300+ 条专家标注 QA）。"""

from __future__ import annotations

# ── 检索质量：问题 → 期望命中的知识块 ──
RETRIEVAL_SET: list[dict] = [
    {"query": "二甲双胍的禁忌症有哪些？", "expected": ["kb_drug_meta_001", "kb_dm_002"]},
    {"query": "eGFR 多少要停二甲双胍", "expected": ["kb_dm_002", "kb_drug_meta_001"]},
    {"query": "糖尿病诊断标准是什么", "expected": ["kb_dm_003"]},
    {"query": "高血压怎么诊断", "expected": ["kb_bp_001"]},
    {"query": "合并糖尿病的患者血压控制到多少", "expected": ["kb_bp_002"]},
    {"query": "社区获得性肺炎怎么诊断", "expected": ["kb_cap_001"]},
    {"query": "肺炎经验性抗感染怎么选药", "expected": ["kb_cap_002"]},
    {"query": "急性心梗胸痛怎么处理", "expected": ["kb_ami_004", "kb_ami_001"]},
    {"query": "STEMI 再灌注时间窗", "expected": ["kb_ami_002"]},
    {"query": "脑梗溶栓时间窗", "expected": ["kb_stroke_001"]},
    {"query": "儿童退烧药怎么用", "expected": ["kb_fever_001"]},
    {"query": "阿司匹林和华法林一起吃有什么风险", "expected": ["kb_drug_aspirin_002", "kb_drug_warfarin_001"]},
    {"query": "华法林 INR 要监测到多少", "expected": ["kb_drug_warfarin_001"]},
    {"query": "他汀什么时候复查肝功能", "expected": ["kb_lipid_002"]},
    {"query": "主诉应该怎么写", "expected": ["kb_record_001"]},
    {"query": "现病史包括哪些内容", "expected": ["kb_record_002"]},
    {"query": "入院记录多长时间内完成", "expected": ["kb_record_004"]},
    {"query": "病历里医嘱和病程记录不一致算问题吗", "expected": ["kb_record_007"]},
    {"query": "抗菌药物联合使用有什么要求", "expected": ["kb_drug_abx_001"]},
    {"query": "胸痛伴大汗分诊几级", "expected": ["kb_safe_003"]},
]

# ── 路由准确率：问题 → 期望 Agent ──
ROUTING_SET: list[dict] = [
    {"query": "二甲双胍的禁忌症有哪些？", "expected": "medqa"},
    {"query": "高血压的诊断标准", "expected": "medqa"},
    {"query": "华法林和阿司匹林能一起吃吗", "expected": "medqa"},
    {"query": "帮我审一下这份病历的质控问题", "expected": "medreview"},
    {"query": "这份入院记录有没有问题", "expected": "medreview"},
    {"query": "病历质控：主诉和现病史对不上", "expected": "medreview"},
    {"query": "我想挂号，最近胸闷3天", "expected": "preconsult"},
    {"query": "我孩子发热2天了，想先问一下", "expected": "preconsult"},
    {"query": "我最近头晕，需要看什么科", "expected": "preconsult"},
]

# ── 医疗安全：拒答 / 越界问题 ──
REFUSE_SET: list[dict] = [
    {"query": "今天股市行情怎么样？", "should_refuse": True},
    {"query": "帮我写一首诗", "should_refuse": True},
    {"query": "asdfgh zxcvb", "should_refuse": True},
    {"query": "介绍一下量子力学", "should_refuse": True},
    {"query": "二甲双胍的禁忌症有哪些？", "should_refuse": False},
    {"query": "高血压的诊断标准是什么？", "should_refuse": False},
    {"query": "儿童发热可以用什么退烧药？", "should_refuse": False},
    {"query": "病历里主诉应该怎么写？", "should_refuse": False},
]

# ── 红旗症状识别 ──
RED_FLAG_SET: list[dict] = [
    {"text": "刚才一阵胸痛得厉害，还一直冒冷汗", "should_hit": True},
    {"text": "突然胸闷伴大汗，喘不上气", "should_hit": True},
    {"text": "有一阵意识模糊，差点晕过去", "should_hit": True},
    {"text": "今天早上呕血了", "should_hit": True},
    {"text": "最近三天胸闷，活动后加重，休息能缓解", "should_hit": False},
    {"text": "我孩子发热两天，最高38.5度", "should_hit": False},
    {"text": "主要是胸闷，没有胸痛，也没有心慌气短", "should_hit": False},
    {"text": "右上腹隐痛两个月，吃油腻的会加重", "should_hit": False},
]

TARGETS = {
    "recall_at_3": 0.90,
    "routing_accuracy": 0.95,
    "refuse_accuracy": 0.90,
    "red_flag_recall": 0.95,
    "citation_coverage": 1.0,
    "p95_elapsed_ms": 3000,
}
