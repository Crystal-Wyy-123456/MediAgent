"""混合检索 + 精排 + 置信度门控 —— RAG 质量的核心链路。

链路：BGE-M3 稠密 TopN + BM25 稀疏 TopN → WeightedRanker 加权融合
      → Cross-Encoder 精排 → TopK → 置信度三向门控

一句话口径：**BGE-M3 只出稠密向量，稀疏向量来自 BM25。**
"""

from __future__ import annotations

import math

from ..config import settings
from ..observability.trace import span
from .embedder import embedder, tokenize
from .knowledge_base import KB
from .reranker import reranker


class SparseIndex:
    """BM25 —— 生产环境用 Milvus 2.4 内置 BM25（传原文即可），这里本地实现。"""

    def __init__(self, docs: list[dict]) -> None:
        self.docs = docs
        self.tf: list[dict[str, int]] = []
        self.df: dict[str, int] = {}
        self.lengths: list[int] = []
        for doc in docs:
            tokens = tokenize(doc["text"])
            counter: dict[str, int] = {}
            for t in tokens:
                counter[t] = counter.get(t, 0) + 1
            self.tf.append(counter)
            self.lengths.append(len(tokens))
            for t in counter:
                self.df[t] = self.df.get(t, 0) + 1
        self.avg_len = sum(self.lengths) / max(1, len(self.lengths))
        self.n = len(docs)
        self.k1 = 1.5
        self.b = 0.75

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))


class HybridRetriever:
    """混合检索器 —— 稠密 + 稀疏双路召回，WeightedRanker 融合，再精排。"""

    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = docs if docs is not None else KB
        self.sparse = SparseIndex(self.docs)
        self.dense_vecs = [embedder.encode(d["text"]) for d in self.docs]

    # ── 单路召回 ──
    def dense_search(self, query: str, limit: int, tenant_id: str = "") -> list[dict]:
        qv = embedder.encode(query)
        scored = []
        for i, doc in enumerate(self.docs):
            if not self._visible(doc, tenant_id):
                continue
            sim = sum(a * b for a, b in zip(qv, self.dense_vecs[i]))
            scored.append((sim, i))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [{**self.docs[i], "dense_score": round(float(s), 6), "hit": "dense"} for s, i in scored[:limit]]

    def sparse_search(self, query: str, limit: int, tenant_id: str = "") -> list[dict]:
        tokens = tokenize(query)
        scored = []
        for i, counter in enumerate(self.sparse.tf):
            if not self._visible(self.docs[i], tenant_id):
                continue
            score = 0.0
            for term in set(tokens):
                freq = counter.get(term)
                if not freq:
                    continue
                denom = freq + self.sparse.k1 * (
                    1 - self.sparse.b + self.sparse.b * self.sparse.lengths[i] / self.sparse.avg_len
                )
                score += self.sparse.idf(term) * freq * (self.sparse.k1 + 1) / denom
            if score > 0:
                scored.append((score, i))
        scored.sort(reverse=True, key=lambda x: x[0])
        top = scored[:limit]
        max_score = top[0][0] if top else 1.0
        return [
            {**self.docs[i], "sparse_score": round(float(s / max_score), 6), "hit": "sparse"}
            for s, i in top
        ]

    @staticmethod
    def _visible(doc: dict, tenant_id: str) -> bool:
        scope = doc.get("tenant_scope")
        return not scope or "*" in scope or tenant_id in scope

    # ── 融合 + 精排 ──
    async def search(self, query: str, tenant_id: str = "", top_n: int | None = None, top_k: int | None = None) -> dict:
        top_n = top_n or settings.retrieval_top_n
        top_k = top_k or settings.retrieval_top_k

        async with span("milvus.dense_search", kind="retrieval", anns_field="dense_vector", limit=top_n):
            dense_hits = self.dense_search(query, top_n, tenant_id)
        async with span("milvus.sparse_search", kind="retrieval", anns_field="sparse_vector", limit=top_n):
            sparse_hits = self.sparse_search(query, top_n, tenant_id)

        async with span("milvus.hybrid_fuse", kind="retrieval", ranker=f"WeightedRanker({settings.dense_weight},{settings.sparse_weight})"):
            fused = self._weighted_rank(dense_hits, sparse_hits, top_n)

        async with span("node.rerank", kind="rerank", model=reranker.provider):
            # 精排输入带上「文献名 + 章节名」：标题本身也是强相关信号，
            # 否则「社区获得性肺炎」这类出处名只在某一段出现，会造成排序偏差。
            scores = reranker.score_batch(
                query,
                [f"{d.get('source', '')} {d.get('section', '')} {d['text']}" for d in fused],
            )
            for doc, score in zip(fused, scores):
                doc["rerank_score"] = round(float(score), 6)
            fused.sort(key=lambda d: d["rerank_score"], reverse=True)
            reranked = fused[:top_k]

        confidence, detail = self.compute_confidence(query, reranked)
        return {
            "query": query,
            "dense_hits": densify(dense_hits),
            "sparse_hits": densify(sparse_hits),
            "fused": densify(fused[:top_n]),
            "docs": reranked,
            "confidence": confidence,
            "confidence_detail": detail,
        }

    def _weighted_rank(self, dense: list[dict], sparse: list[dict], limit: int) -> list[dict]:
        """WeightedRanker 加权融合：稠密 0.7 / 稀疏 0.3。"""
        merged: dict[str, dict] = {}
        for rank, doc in enumerate(dense):
            item = merged.setdefault(doc["chunk_id"], {**doc, "dense_score": 0.0, "sparse_score": 0.0})
            item["dense_score"] = max(item.get("dense_score", 0.0), doc.get("dense_score", 0.0))
            del rank
        for doc in sparse:
            item = merged.setdefault(doc["chunk_id"], {**doc, "dense_score": 0.0, "sparse_score": 0.0})
            item["sparse_score"] = max(item.get("sparse_score", 0.0), doc.get("sparse_score", 0.0))

        # 归一化两路分数到 0~1 再加权（不同的量纲不能直接相加）
        max_dense = max((d.get("dense_score", 0.0) for d in merged.values()), default=1.0) or 1.0
        max_sparse = max((d.get("sparse_score", 0.0) for d in merged.values()), default=1.0) or 1.0
        for item in merged.values():
            item["fused_score"] = round(
                settings.dense_weight * (item.get("dense_score", 0.0) / max_dense)
                + settings.sparse_weight * (item.get("sparse_score", 0.0) / max_sparse),
                6,
            )
        return sorted(merged.values(), key=lambda d: d["fused_score"], reverse=True)[:limit]

    @staticmethod
    def compute_confidence(query: str, docs: list[dict]) -> tuple[float, dict]:
        """置信度 = 0.45*精排最高分 + 0.25*Top3均分 + 0.15*词项覆盖率 + 0.15*文档数因子。"""
        if not docs:
            return 0.0, {"reason": "无召回结果"}
        scores = [d.get("rerank_score", 0.0) for d in docs]
        top = scores[0]
        mean_top3 = sum(scores[:3]) / len(scores[:3])
        q_set = set(tokenize(query))
        d_set = set(tokenize(" ".join(d["text"] for d in docs[:3])))
        coverage = len(q_set & d_set) / max(1, len(q_set))
        count_factor = min(1.0, len(docs) / 3)
        conf = 0.45 * top + 0.25 * mean_top3 + 0.15 * coverage + 0.15 * count_factor
        conf = round(max(0.0, min(1.0, conf)), 4)
        return conf, {
            "top_score": round(top, 4),
            "mean_top3": round(mean_top3, 4),
            "term_coverage": round(coverage, 4),
            "doc_count": len(docs),
        }


def densify(docs: list[dict]) -> list[dict]:
    """裁掉冗余字段，减少 SSE / JSON 体积。"""
    keep = ("chunk_id", "doc_id", "source", "doc_type", "department", "year",
            "chapter", "section", "page", "dense_score", "sparse_score", "fused_score", "rerank_score")
    out = []
    for doc in docs:
        item = {k: doc[k] for k in keep if k in doc}
        item["text"] = doc.get("text", "")[:160]
        out.append(item)
    return out


_retriever: HybridRetriever | None = None


def get_retriever() -> HybridRetriever:
    """懒加载：首次检索时才建索引（对应设计方案的图懒加载原则）。"""
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever
