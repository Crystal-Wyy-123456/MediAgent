"""知识库 MCP Server —— 把指南检索、药品说明书、相互作用查询封装成独立 Server。

Agent 不 import 这里的任何实现，只通过注册中心按名字调用。
"""

from __future__ import annotations

from ...rag.knowledge_base import DOCUMENTS, KB
from ...rag.retriever import get_retriever
from ..framework import ToolServer

knowledge_mcp = ToolServer(
    name="medical-kb",
    version="1.0.0",
    instructions="院内知识库工具集：指南检索、药品相互作用、说明书查询。",
)


@knowledge_mcp.tool(
    name="search_guideline",
    description="检索临床指南知识库，返回带来源、章节与页码的原文片段。",
)
async def search_guideline(
    query: str,
    department: str | None = None,
    year_from: int | None = None,
    top_k: int = 10,
) -> dict:
    """检索临床指南知识库。

    Args:
        query: 检索问题
        department: 限定科室，可选（如「心血管内科」）
        year_from: 只返回该年份之后的指南（留空表示不过滤）
        top_k: 返回条数
    """
    retriever = get_retriever()
    result = await retriever.search(query, top_k=max(1, min(top_k, 20)))
    docs = result["docs"]
    if department:
        docs = [d for d in docs if d.get("department") == department] or docs
    if year_from:
        filtered = [d for d in docs if int(d.get("year", 0)) >= year_from]
        docs = filtered if len(filtered) >= 2 else docs
    return {
        "query": query,
        "confidence": result["confidence"],
        "confidence_detail": result["confidence_detail"],
        "pipeline": {
            "anns_fields": ["dense_vector", "sparse_vector"],
            "dense_candidates": len(result["dense_hits"]),
            "sparse_candidates": len(result["sparse_hits"]),
            "fused": len(result["fused"]),
            "reranked": len(docs),
        },
        "hits": [
            {
                "chunk_id": d["chunk_id"],
                "source": d["source"],
                "chapter": d["chapter"],
                "section": d["section"],
                "page": d["page"],
                "year": d["year"],
                "department": d["department"],
                "text": d["text"],
                "score": d.get("rerank_score", 0.0),
            }
            for d in docs
        ],
    }


@knowledge_mcp.tool(name="get_drug_interaction", description="查询两种药物的相互作用与配伍禁忌。")
def get_drug_interaction(drug_a: str, drug_b: str) -> dict:
    """查询两种药物的相互作用与配伍禁忌。"""
    pair = {drug_a.strip(), drug_b.strip()}
    for item in DRUG_INTERACTIONS:
        if pair == set(item["pair"]):
            return {"found": True, "drugs": sorted(pair), "level": item["level"], "description": item["desc"], "source": item["source"]}
    return {
        "found": False,
        "drugs": sorted(pair),
        "level": "unknown",
        "description": "本地相互作用库未收录该组合，建议查询最新版说明书或咨询临床药师。",
        "source": "（未命中本地相互作用库）",
    }


@knowledge_mcp.tool(name="get_drug_monograph", description="查询药品说明书要点：禁忌、用法用量、注意事项。")
def get_drug_monograph(drug: str) -> dict:
    """查询药品说明书要点：禁忌、用法用量、注意事项。"""
    hits = [c for c in KB if c["doc_type"] == "label" and (drug in c["source"] or drug in c["text"])]
    if not hits:
        return {"found": False, "drug": drug, "sections": []}
    return {
        "found": True,
        "drug": drug,
        "source": hits[0]["source"],
        "sections": [
            {"chapter": h["chapter"], "section": h["section"], "page": h["page"], "text": h["text"]} for h in hits[:6]
        ],
    }


@knowledge_mcp.tool(name="list_departments", description="列出知识库覆盖的科室与文献规模。")
def list_departments() -> dict:
    """列出知识库覆盖的科室与文献规模。"""
    departments: dict[str, int] = {}
    for doc in DOCUMENTS.values():
        departments[doc["department"]] = departments.get(doc["department"], 0) + 1
    return {"departments": departments, "documents": len(DOCUMENTS), "chunks": len(KB)}


DRUG_INTERACTIONS = [
    {
        "pair": ["阿司匹林", "华法林"],
        "level": "contraindicated-caution",
        "desc": "阿司匹林与华法林合用可显著增加出血风险，必须联用时需评估出血风险并密切监测 INR 与出血征象。",
        "source": "华法林钠片说明书 · 药物相互作用",
    },
    {
        "pair": ["阿司匹林", "布洛芬"],
        "level": "caution",
        "desc": "布洛芬可能竞争性抑制阿司匹林的抗血小板作用，长期合用会削弱心血管保护作用。",
        "source": "阿司匹林肠溶片说明书 · 药物相互作用",
    },
    {
        "pair": ["二甲双胍", "碘造影剂"],
        "level": "caution",
        "desc": "使用碘造影剂前后应暂停二甲双胍，检查后至少 48 小时复查肾功能无恶化方可恢复。",
        "source": "盐酸二甲双胍片说明书 · 注意事项",
    },
    {
        "pair": ["头孢", "酒精"],
        "level": "contraindicated-caution",
        "desc": "头孢类与酒精可诱发双硫仑样反应，用药期间及停药后 7 天内应禁酒。",
        "source": "抗菌药物临床应用指导原则 · 用药安全",
    },
    {
        "pair": ["华法林", "阿莫西林"],
        "level": "caution",
        "desc": "部分抗菌药物可影响肠道菌群维生素 K 合成而增强华法林抗凝作用，需加强 INR 监测。",
        "source": "华法林钠片说明书 · 药物相互作用",
    },
]
