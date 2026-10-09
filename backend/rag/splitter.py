"""智能分块 —— 父子块策略。

小块保召回精度，父块保上下文完整。这里只依赖标准库，保证零依赖即可运行；
生产环境换 LangChain 的 ParentDocumentRetriever 即可（接口一致）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    chunk_id: str
    parent_id: str
    text: str
    meta: dict = field(default_factory=dict)


def split_paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", text or "")
    return [b.strip() for b in blocks if b.strip()]


def split_parent_child(text: str, child_size: int = 220, overlap: int = 40) -> list[Chunk]:
    """父块 = 自然段；子块 = 段内按句子边界滑窗切分。"""
    chunks: list[Chunk] = []
    for p_idx, paragraph in enumerate(split_paragraphs(text)):
        parent_id = f"p_{p_idx:03d}"
        sentences = [s for s in re.split(r"(?<=[。；！？])", paragraph) if s.strip()]
        buffer = ""
        c_idx = 0
        for sentence in sentences:
            if len(buffer) + len(sentence) > child_size and buffer:
                chunks.append(Chunk(f"{parent_id}_c{c_idx:02d}", parent_id, buffer.strip()))
                c_idx += 1
                buffer = buffer[-overlap:] if overlap else ""
            buffer += sentence
        if buffer.strip():
            chunks.append(Chunk(f"{parent_id}_c{c_idx:02d}", parent_id, buffer.strip()))
    return chunks
