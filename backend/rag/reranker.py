"""Cross-Encoder 精排 —— BGE-Reranker 的本地替代实现。

精排解决的是**精确率**（排得准），与召回阶段的 Bi-Encoder 互补而非替代。
本地实现用「词项重合 + IDF 加权 + 短语邻近」近似交叉编码的打分行为。
"""

from __future__ import annotations

import math

from ..config import settings
from .embedder import tokenize
from .knowledge_base import KB


class LocalReranker:
    provider = "local-cross"

    def __init__(self) -> None:
        self._idf: dict[str, float] = {}

    def fit(self, corpus: list[str]) -> None:
        n = max(1, len(corpus))
        df: dict[str, int] = {}
        for doc in corpus:
            for token in set(tokenize(doc)):
                df[token] = df.get(token, 0) + 1
        self._idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}

    def score(self, query: str, doc: str) -> float:
        q_tokens = tokenize(query)
        d_tokens = tokenize(doc)
        if not q_tokens or not d_tokens:
            return 0.0
        q_set = set(q_tokens)
        d_set = set(d_tokens)
        overlap = q_set & d_set
        if not overlap:
            return 0.0
        weight = sum(self._idf.get(t, 1.2) for t in overlap)
        denom = sum(self._idf.get(t, 1.2) for t in q_set) or 1.0
        coverage = weight / denom

        # 短语邻近奖励：查询中的连续片段若整体出现，说明强相关
        phrase_bonus = 0.0
        q = (query or "").strip()
        for size in (6, 4, 3):
            hit = False
            for i in range(0, max(0, len(q) - size + 1)):
                frag = q[i : i + size]
                if len(frag.strip()) == size and frag in doc:
                    phrase_bonus += 0.08
                    hit = True
                    break
            if hit:
                break

        length_penalty = 1.0 - min(0.15, max(0, len(d_tokens) - 200) / 2000)
        raw = (0.82 * coverage + phrase_bonus + 0.18 * min(1.0, len(overlap) / 12)) * length_penalty
        return max(0.0, min(1.0, raw))

    def score_batch(self, query: str, docs: list[str]) -> list[float]:
        return [self.score(query, d) for d in docs]


class BgeReranker:  # pragma: no cover - 需要额外权重，默认不启用
    provider = "bge-reranker"

    def __init__(self, model_name: str | None = None) -> None:
        from sentence_transformers import CrossEncoder  # type: ignore

        self.model = CrossEncoder(model_name or settings.rerank_model)

    def fit(self, corpus: list[str]) -> None:
        return None

    def score(self, query: str, doc: str) -> float:
        return float(self.model.predict([(query, doc)])[0])

    def score_batch(self, query: str, docs: list[str]) -> list[float]:
        return [float(s) for s in self.model.predict([(query, d) for d in docs])]


def build_reranker():
    if settings.rerank_provider.lower() == "bge":
        try:
            return BgeReranker()
        except Exception:  # noqa: BLE001
            pass
    return LocalReranker()


reranker = build_reranker()
reranker.fit([c["text"] for c in KB])
