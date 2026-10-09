"""向量库接入层。

默认使用内置轻量索引（backend/rag/retriever.py），保证零外部依赖即可运行；
配置 MILVUS_URI 后即可切到 Milvus 2.4（稠密 dense_vector + 内置 BM25 sparse_vector），
检索接口签名保持不变 —— 这正是「换实现不改业务代码」的落点。
"""

from __future__ import annotations

from ..config import settings
from ..rag.knowledge_base import KB, kb_stats


def collection_stats() -> dict:
    stats = kb_stats()
    return {
        "backend": "milvus" if settings.milvus_uri else "builtin-hybrid-index",
        "uri": settings.milvus_uri or "（未配置，使用内置索引）",
        "collection": settings.milvus_collection,
        "dense_field": "dense_vector",
        "sparse_field": "sparse_vector",
        "ranker": f"WeightedRanker({settings.dense_weight}, {settings.sparse_weight})",
        "indexed_chunks": len(KB),
        **stats,
    }


def health() -> dict:
    return {"status": "ok", "backend": "milvus" if settings.milvus_uri else "builtin"}
