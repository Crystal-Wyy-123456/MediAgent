"""检索链路：混合召回 → 精排 → 置信度三向门控。"""

from __future__ import annotations

import pytest

from backend.config import settings
from backend.rag.retriever import get_retriever


def gate(conf: float) -> str:
    if conf >= settings.confidence_generate:
        return "generate"
    if conf >= settings.confidence_refuse:
        return "web_search"
    return "refuse"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_chunk"),
    [
        ("二甲双胍的禁忌症有哪些？", "kb_drug_meta_001"),
        ("高血压的诊断标准是什么？", "kb_bp_001"),
        ("儿童发热可以用什么退烧药？", "kb_fever_001"),
    ],
)
async def test_top3_recall(query: str, expected_chunk: str):
    result = await get_retriever().search(query)
    ids = [d["chunk_id"] for d in result["docs"]]
    assert expected_chunk in ids, f"{query} -> {ids}"


@pytest.mark.asyncio
async def test_out_of_domain_refuses():
    result = await get_retriever().search("今天股市行情怎么样？")
    assert gate(result["confidence"]) == "refuse"


@pytest.mark.asyncio
async def test_in_domain_generates():
    result = await get_retriever().search("二甲双胍的禁忌症有哪些？")
    assert gate(result["confidence"]) == "generate"


@pytest.mark.asyncio
async def test_ranking_prefers_section_title():
    """精排输入带上文献名+章节名，避免「出处名只出现在某一段」造成的排序偏差。"""
    result = await get_retriever().search("社区获得性肺炎首选什么抗生素？")
    assert result["docs"][0]["section"].startswith("4.2")
