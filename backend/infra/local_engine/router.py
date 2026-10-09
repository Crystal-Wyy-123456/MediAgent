"""L2 意图路由 + Query 分类的判据。"""

from __future__ import annotations

import re

SOCIAL_WORDS = {"你好", "您好", "谢谢", "在吗", "hi", "hello", "辛苦了", "早上好", "再见"}

MEDREVIEW_HINTS = [
    "病历", "质控", "入院记录", "病程记录", "病历质控", "审病历", "查病历",
    "出院小结", "手术记录", "病案首页", "审查",
]
PRECONSULT_HINTS = [
    "挂号", "预问诊", "问诊", "我最近", "我这两天", "我儿子", "我女儿", "我感觉",
    "我想看", "看一下病", "咨询病情", "症状", "疼", "发热", "咳嗽", "头晕",
    "不舒服", "帮我挂号",
]
PIPELINE_HINTS = ["先问诊再质控", "预问诊后质控", "全流程", "整条链路", "全链路"]


def _score(query: str, hints: list[str]) -> int:
    return sum(1 for h in hints if h in query)


def query_type(payload: dict) -> dict:
    query = (payload.get("query") or "").strip()
    cleaned = re.sub(r"[\s，。！？、,.!?~]+", "", query)
    if cleaned in SOCIAL_WORDS or (len(cleaned) <= 4 and any(w in cleaned for w in SOCIAL_WORDS)):
        return {"type": "CHITCHAT", "reason": "短句社交寒暄，无知识检索意图"}
    return {"type": "KNOWLEDGE", "reason": "包含医学知识检索意图"}


def route_decision(payload: dict) -> dict:
    query = payload.get("query") or ""
    pipeline = None
    if _score(query, PIPELINE_HINTS) > 0:
        pipeline = "preconsult_review"

    review_score = _score(query, MEDREVIEW_HINTS)
    consult_score = _score(query, PRECONSULT_HINTS)
    has_guideline_word = any(w in query for w in ["指南", "说明书", "禁忌", "适应证", "剂量", "相互作用", "推荐", "诊断标准"])

    if review_score and review_score >= consult_score:
        agent, reason, conf = "medreview", "检测到病历质控相关表述（病历/审查/记录）", 0.94
    elif consult_score and not has_guideline_word:
        agent, reason, conf = "preconsult", "检测到患者主诉与问诊意图", 0.9
    elif has_guideline_word:
        agent, reason, conf = "medqa", "检测到指南/药品知识查询意图", 0.95
    else:
        agent, reason, conf = "medqa", "默认归为医学知识问答", 0.66

    return {
        "agent_type": agent,
        "pipeline_mode": pipeline,
        "reason": reason,
        "confidence": conf,
    }
