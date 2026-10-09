"""MedQA 的生成侧实现 —— 检索增强作答 + 强制引用 + 拒答。"""

from __future__ import annotations

import re

SENT_SPLIT = re.compile(r"[。；;！!？?]")
STOPWORDS = set("的了和与及或是在有为对能可将会于其之而且并以及对于根据以下哪些什么怎么如何请问")


def _terms(text: str) -> set[str]:
    text = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", text or "")
    grams = {text[i : i + 2] for i in range(len(text) - 1)}
    chars = {c for c in text if c not in STOPWORDS}
    return {g for g in grams if not (g[0] in STOPWORDS and g[1] in STOPWORDS)} | chars


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text or "") if len(s.strip()) >= 8]


def _pick_sentence(doc_text: str, query: str) -> str:
    terms = _terms(query)
    sentences = _split_sentences(doc_text)
    if not sentences:
        return (doc_text or "").strip()
    scored = []
    for sent in sentences:
        overlap = len(terms & _terms(sent))
        scored.append((overlap + min(len(sent), 60) / 400, sent))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _risk_note(query: str) -> str:
    if any(w in query for w in ["胸痛", "呼吸困难", "意识", "呕血", "大出血", "高热不退"]):
        return "以上为知识库检索结果，若患者已出现上述危急表现，请立即按急诊流程处理，不要等待线上结论。"
    return "以上结论均来自知识库原文，具体用药请结合患者个体情况并核对最新版说明书。"


def answer_with_citations(payload: dict) -> dict:
    query = payload.get("query", "")
    docs = payload.get("docs") or []
    rules = payload.get("rules", "")

    if not docs:
        return {"answer": "知识库中没有检索到与该问题相关的内容，建议转人工复核。", "citations": [], "refusal": True}

    body_parts: list[str] = []
    citations: list[dict] = []
    seen: set[str] = set()

    for idx, doc in enumerate(docs[:4], start=1):
        sentence = _pick_sentence(doc.get("text", ""), query)
        key = sentence[:24]
        if key in seen:
            continue
        seen.add(key)
        body_parts.append(f"{len(body_parts) + 1}. {sentence}[{len(citations) + 1}]")
        citations.append(
            {
                "index": len(citations) + 1,
                "source": doc.get("source", ""),
                "chapter": doc.get("chapter", ""),
                "page": doc.get("page"),
                "snippet": sentence,
                "score": round(float(doc.get("score", 0.0)), 4),
                "doc_id": doc.get("doc_id", doc.get("chunk_id", "")),
            }
        )

    answer = (
        f"针对「{query}」，知识库中相关条目如下：\n"
        + "\n".join(body_parts)
        + f"\n\n{_risk_note(query)}"
    )
    if rules:
        answer += ""
    return {"answer": answer, "citations": citations, "refusal": False}


def refusal(payload: dict) -> dict:
    query = payload.get("query", "")
    reason = payload.get("reason", "检索置信度不足")
    return {
        "answer": (
            f"抱歉，知识库对「{query}」的覆盖不足（{reason}），为避免给出无依据的医学结论，"
            "我不做推测性回答。建议：① 补充更具体的药品名/指南编号/科室；② 转人工由临床药师或专科医师确认。"
        ),
        "citations": [],
        "refusal": True,
    }


def chitchat(payload: dict, prompt: str = "") -> str:
    query = (payload.get("query") or "").strip()
    if any(w in query for w in ["谢谢", "辛苦", "感谢"]):
        return "不客气。我随时可以帮你查指南、查药品说明书或发起预问诊，直接说问题就行。"
    if any(w in query for w in ["再见", "拜拜"]):
        return "再见，祝工作顺利。需要时随时叫我。"
    return (
        "你好，我是 MediAgent 医师助手。我可以：\n"
        "① 检索临床指南与药品说明书（均带来源与页码）；\n"
        "② 对住院病历做内涵质控；\n"
        "③ 发起门诊预问诊并支持医生接管。\n"
        "把具体问题发给我就行。"
    )
