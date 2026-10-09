"""MCP 工具注册中心 —— Agent 只按名字调用，不 import 任何具体实现。

统一超时 + 重试（这就是三层降级里的第一层兜底）。
transport 可插拔：inproc（默认，进程内调用）/ stdio（标准 MCP 协议）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ..config import settings
from ..infra.retry import with_retry
from ..observability.logger import log_event
from ..observability.trace import span
from .framework import ToolSpec


class MCPToolRegistry:
    def __init__(self, transport: str | None = None) -> None:
        self.transport = (transport or settings.mcp_transport).lower()
        self._servers: dict[str, Any] = {}
        self._schemas: dict[str, ToolSpec] = {}
        self._server_of: dict[str, str] = {}
        self._discovered = False

    # ── 服务发现 ──
    async def discover(self) -> None:
        if self.transport == "stdio":
            ok = await self._discover_stdio()
            if ok:
                self._discovered = True
                return
            log_event("mcp_stdio_unavailable", fallback="inproc")
        await self._discover_inproc()
        self._discovered = True

    async def _discover_inproc(self) -> None:
        from .servers.knowledge_mcp import knowledge_mcp
        from .servers.web_search_mcp import web_search_mcp

        for server in (knowledge_mcp, web_search_mcp):
            self._servers[server.name] = server
            for spec in server.list_tools():
                self._schemas[spec.name] = spec
                self._server_of[spec.name] = server.name

    async def _discover_stdio(self) -> bool:  # pragma: no cover - 需要官方 mcp SDK
        """标准 MCP 协议发现：连不上就返回 False，由调用方回落进程内 transport。"""
        try:
            from mcp import ClientSession, StdioServerParameters  # type: ignore
            from mcp.client.stdio import stdio_client  # type: ignore
        except ImportError:
            return False
        try:
            from .servers import run_mcp_server

            for name in ("medical-kb", "web-search"):
                params = StdioServerParameters(
                    command="python",
                    args=["-m", "backend.tools.servers.run_mcp_server", name],
                )
                ctx = stdio_client(params)
                read, write = await ctx.__aenter__()
                session = ClientSession(read, write)
                await session.__aenter__()
                await session.initialize()
                tools = await session.list_tools()
                for tool in tools.tools:
                    self._schemas[tool.name] = ToolSpec(
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.inputSchema,
                        func=None,  # stdio 模式下由 session 转发
                        server=name,
                    )
                    self._server_of[tool.name] = name
                self._servers[name] = session
            del run_mcp_server
            return bool(self._schemas)
        except Exception as exc:  # noqa: BLE001
            log_event("mcp_stdio_failed", error=repr(exc))
            return False

    # ── 对外接口 ──
    def list_tools(self) -> list[dict]:
        return [spec.to_dict() for spec in self._schemas.values()]

    def has(self, name: str) -> bool:
        return name in self._schemas

    async def call(self, tool_name: str, args: dict | None = None) -> Any:
        args = args or {}
        if not self._discovered:
            await self.discover()
        if tool_name not in self._schemas:
            raise KeyError(f"MCP 工具未找到：{tool_name}")
        server_name = self._server_of.get(tool_name, "")
        async with span(f"mcp.{tool_name}", kind="tool", server=server_name, args=_brief(args)):
            async def _invoke() -> Any:
                if self.transport == "stdio" and hasattr(self._servers.get(server_name), "call_tool"):
                    result = await asyncio.wait_for(
                        self._servers[server_name].call_tool(tool_name, args), timeout=settings.tool_timeout_s
                    )
                    return _unwrap_mcp_result(result)
                return await asyncio.wait_for(
                    self._servers[server_name].call_tool(tool_name, args), timeout=settings.tool_timeout_s
                )

            return await with_retry(_invoke, max_retries=settings.tool_max_retries, label=f"mcp.{tool_name}")


def _brief(args: dict) -> dict:
    out = {}
    for key, value in list(args.items())[:6]:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        out[key] = text[:60]
    return out


def _unwrap_mcp_result(result: Any) -> Any:
    """标准 MCP 返回 {content:[{type:'text',text:'...'}]}，这里还原成 dict。"""
    content = getattr(result, "content", None)
    if not content:
        return result
    first = content[0]
    text = getattr(first, "text", None)
    if text is None:
        return result
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


mcp_registry = MCPToolRegistry()
