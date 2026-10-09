"""把内置工具注册成**标准 MCP Server**（stdio transport）。

用法：
    python -m backend.tools.servers.run_mcp_server medical-kb
    python -m backend.tools.servers.run_mcp_server web-search

需要官方 SDK：pip install mcp
装好后把 .env 里的 MCP_TRANSPORT 改成 stdio，注册中心就会走标准 MCP 协议。
"""

from __future__ import annotations

import sys


def build(name: str):
    from mcp.server.fastmcp import FastMCP  # type: ignore

    from .knowledge_mcp import knowledge_mcp
    from .web_search_mcp import web_search_mcp

    source = {"medical-kb": knowledge_mcp, "web-search": web_search_mcp}.get(name)
    if source is None:
        raise SystemExit(f"未知的 MCP Server：{name}（可选：medical-kb / web-search）")

    server = FastMCP(source.name)
    for spec in source.list_tools():
        server.add_tool(spec.func, name=spec.name, description=spec.description)
    return server


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "medical-kb"
    build(target).run()
