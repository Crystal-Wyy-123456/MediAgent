"""向量编码 —— BGE-M3 稠密向量的本地替代实现。

真实的 BGE-M3 需要下载约 2GB 权重；默认用**字符 n-gram 哈希编码**代替：
确定性、零下载、跨平台一致，检索行为与稠密向量同构。
装好 sentence-transformers 后把 EMBEDDING_PROVIDER 改成 bge 即可切到真模型。
"""

from __future__ import annotations

import hashlib
import math
import re

from ..config import settings

_TOKEN_RE = re.compile(r"[\u4e00-\u9fa5]|[A-Za-z]+|\d+(?:\.\d+)?")


def tokenize(text: str) -> list[str]:
    """中文按单字 + 二元组，英文/数字按词 —— 兼顾召回与精确匹配。"""
    text = (text or "").lower()
    raw = _TOKEN_RE.findall(text)
    tokens = list(raw)
    for i in range(len(raw) - 1):
        tokens.append(raw[i] + raw[i + 1])
    return tokens


class LocalEmbedder:
    provider = "local-hash"

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or settings.embedding_dim

    def _hash(self, token: str) -> int:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "little") % self.dim

    def encode(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = tokenize(text)
        if not tokens:
            return vec
        for token in tokens:
            idx = self._hash(token)
            sign = 1.0 if self._hash(token + "#") % 2 == 0 else -1.0
            vec[idx] += sign * (1.0 + 0.4 * math.log(1 + len(token)))
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(t) for t in texts]


class BgeEmbedder:  # pragma: no cover - 需要额外权重，默认不启用
    provider = "bge-m3"

    def __init__(self, model_name: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self.model = SentenceTransformer(model_name or settings.embedding_model)

    def encode(self, text: str) -> list[float]:
        return self.model.encode([text], normalize_embeddings=True)[0].tolist()

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


def build_embedder():
    if settings.embedding_provider.lower() == "bge":
        try:
            return BgeEmbedder()
        except Exception:  # noqa: BLE001 - 权重缺失时自动回落，保证本地可跑
            pass
    return LocalEmbedder()


embedder = build_embedder()
