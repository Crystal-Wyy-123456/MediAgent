"""联网搜索 MCP Server —— 知识库覆盖不足时的兜底。

默认返回本地整理的外部检索线索（来源标记 external-index），
配置真实搜索 API（如 Bing/SerpAPI）后替换 `_provider_call` 即可。
"""

from __future__ import annotations

from ..framework import ToolServer

web_search_mcp = ToolServer(
    name="web-search",
    version="1.0.0",
    instructions="联网检索兜底工具：仅用于知识库覆盖不足的场景。",
)


@web_search_mcp.tool(name="web_search", description="联网搜索医学资料（知识库覆盖不足时的兜底）。")
async def web_search(query: str, max_results: int = 5) -> dict:
    """联网搜索医学资料（知识库覆盖不足时的兜底）。

    Args:
        query: 检索问题
        max_results: 返回条数
    """
    results = await _provider_call(query, max_results)
    return {
        "provider": "external-web-index",
        "verified": False,
        "query": query,
        "results": results,
        "notice": "外部检索结果仅作线索，需由医师核对权威来源后使用。",
    }


async def _provider_call(query: str, max_results: int) -> list[dict]:
    """返回外部检索线索。真实接入点：把这里换成 HTTP 调用即可。"""
    seeds = [
        {
            "title": f"「{query}」相关诊疗要点汇总（公开科普资料）",
            "snippet": "该问题在院内知识库中未检索到直接依据，联网结果仅作线索，需由医师核对权威来源后使用。",
            "url": "https://example.org/health/topic",
            "rank": 1,
        },
        {
            "title": f"国家卫生健康委相关诊疗规范（公开版）",
            "snippet": "公开规范文件可作为补充参考，但版本与适用范围需与院内实际诊疗规范核对。",
            "url": "https://example.org/nhc/standard",
            "rank": 2,
        },
    ]
    return seeds[: max(1, max_results)]
