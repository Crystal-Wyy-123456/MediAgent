"""极简 MCP 兼容工具框架。

为什么要有这一层：Agent 不应该 import 任何具体工具实现，只通过**名字 + Schema**
调用工具。新增一个工具只需注册，三个 Agent 的代码零改动。

这套框架与官方 `mcp` 包的 FastMCP 接口同构：
  · tool 装饰器从函数签名生成 JSON Schema
  · list_tools() / call_tool() 与 MCP 协议一一对应
装好官方 SDK 后（pip install mcp），servers/run_mcp_server.py 可把同样的函数
注册成标准 MCP Server，用 stdio transport 跑 —— 工具定义零改动。
"""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import create_model


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    func: Callable[..., Any]
    server: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "server": self.server,
        }


@dataclass
class ToolServer:
    name: str
    version: str = "1.0.0"
    instructions: str = ""
    tools: dict[str, ToolSpec] = field(default_factory=dict)

    def tool(self, name: str | None = None, description: str | None = None):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or fn.__name__
            spec = ToolSpec(
                name=tool_name,
                description=(description or (fn.__doc__ or "").strip().split("\n")[0]),
                input_schema=_schema_from_signature(fn),
                func=fn,
                server=self.name,
            )
            self.tools[tool_name] = spec
            return fn

        return deco

    def list_tools(self) -> list[ToolSpec]:
        return list(self.tools.values())

    async def call_tool(self, name: str, args: dict) -> Any:
        spec = self.tools.get(name)
        if spec is None:
            raise KeyError(f"工具未注册：{name}")
        if inspect.iscoroutinefunction(spec.func):
            return await spec.func(**args)
        return await asyncio.get_running_loop().run_in_executor(None, lambda: spec.func(**args))


_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _schema_from_signature(fn: Callable[..., Any]) -> dict:
    """从函数签名生成 JSON Schema —— 与 MCP Tool Schema 完全一致。"""
    try:
        from typing import get_args, get_origin

        fields: dict[str, tuple[Any, Any]] = {}
        for param in inspect.signature(fn).parameters.values():
            if param.name in {"self", "cls"}:
                continue
            annotation = param.annotation if param.annotation is not inspect.Parameter.empty else str
            origin = get_origin(annotation)
            if origin is not None:  # 处理 Optional[str] / list[str]
                args = [a for a in get_args(annotation) if a is not type(None)]
                annotation = args[0] if args else str
            default = param.default if param.default is not inspect.Parameter.empty else ...
            fields[param.name] = (annotation, default)
        model = create_model(f"{fn.__name__}_args", **fields)  # type: ignore[call-overload]
        schema = model.model_json_schema()
        schema.pop("title", None)
        return schema
    except Exception:  # noqa: BLE001 - Schema 生成失败不影响调用
        return {"type": "object", "properties": {}, "additionalProperties": True}


def describe_tools(specs: list[ToolSpec]) -> list[dict]:
    return [s.to_dict() for s in specs]


def pretty_schema(spec: ToolSpec) -> str:
    return json.dumps(spec.input_schema, ensure_ascii=False, indent=2)
