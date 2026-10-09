"""自研轻量 Trace —— request_id 全链路透传 + 节点埋点 + 结构化日志落表。

只解决三件事：
  1. 这次请求经过了哪些节点（span 树）
  2. 每个节点花了多久 / 多少 Token
  3. 失败在哪一步

全部用 Python 标准库实现，不引入额外的观测服务 —— 与「上量之前中间件是负债」
是同一条工程原则。
"""

from __future__ import annotations

import contextvars
import functools
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
_current_trace: contextvars.ContextVar["Trace | None"] = contextvars.ContextVar("current_trace", default=None)
_span_stack: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar("span_stack", default=())


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:16]}"


@dataclass
class Span:
    span_id: str
    name: str
    kind: str
    parent: str | None
    depth: int
    elapsed_ms: float
    ok: bool = True
    error: str | None = None
    token_in: int = 0
    token_out: int = 0
    meta: dict = field(default_factory=dict)
    started_at: float = 0.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["elapsed_ms"] = round(self.elapsed_ms, 2)
        return data


@dataclass
class Trace:
    request_id: str
    query: str = ""
    tenant_id: str = ""
    user_id: str = ""
    session_id: str = ""
    agent_type: str = ""
    pipeline_mode: str | None = None
    route_level: str = ""
    route_reason: str = ""
    status: str = "running"
    fallback_used: bool = False
    token_in: int = 0
    token_out: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    spans: list[Span] = field(default_factory=list)
    content_preview: str = ""
    citations: int = 0

    @property
    def elapsed_ms(self) -> float:
        end = self.finished_at or time.time()
        return round((end - self.started_at) * 1000, 2)

    @property
    def total_tokens(self) -> int:
        return self.token_in + self.token_out

    def tree(self) -> list[dict]:
        """按层级还原 span 树，前端可直接渲染瀑布图。"""
        by_parent: dict[str | None, list[Span]] = {}
        for s in sorted(self.spans, key=lambda x: x.started_at):
            by_parent.setdefault(s.parent, []).append(s)
        out: list[dict] = []

        def walk(parent: str | None) -> None:
            for s in by_parent.get(parent, []):
                node = s.to_dict()
                out.append(node)
                walk(s.span_id)

        walk(None)
        return out

    def to_dict(self, with_spans: bool = True) -> dict:
        data = {
            "request_id": self.request_id,
            "query": self.query,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "agent_type": self.agent_type,
            "pipeline_mode": self.pipeline_mode,
            "route_level": self.route_level,
            "route_reason": self.route_reason,
            "status": self.status,
            "fallback_used": self.fallback_used,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "total_tokens": self.total_tokens,
            "elapsed_ms": self.elapsed_ms,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "content_preview": self.content_preview,
            "citations": self.citations,
            "span_count": len(self.spans),
        }
        if with_spans:
            data["spans"] = self.tree()
        return data


class TraceStore:
    """内存环形缓冲 + 落库（本地部署用 SQLite；生产换 PostgreSQL 同构）。"""

    def __init__(self, max_items: int = 500) -> None:
        self._items: "deque[Trace]" = deque(maxlen=max_items)
        self._index: dict[str, Trace] = {}
        self._sink: Callable[[Trace], None] | None = None

    def bind_sink(self, sink: Callable[[Trace], None]) -> None:
        self._sink = sink

    def add(self, trace: Trace) -> None:
        if len(self._items) == self._items.maxlen:
            evicted = self._items[0]
            self._index.pop(evicted.request_id, None)
        self._items.append(trace)
        self._index[trace.request_id] = trace
        if self._sink:
            try:
                self._sink(trace)
            except Exception:  # 观测不能影响主流程
                pass

    def get(self, request_id: str) -> Trace | None:
        return self._index.get(request_id)

    def list(self, limit: int = 100) -> list[Trace]:
        return list(reversed(self._items))[:limit]

    def stats(self) -> dict:
        items = list(self._items)
        if not items:
            return {
                "requests": 0,
                "avg_elapsed_ms": 0.0,
                "p95_elapsed_ms": 0.0,
                "fallback_rate": 0.0,
                "error_rate": 0.0,
                "total_tokens": 0,
                "route_distribution": {},
                "agent_distribution": {},
                "kind_duration_ms": {},
            }
        elapsed = sorted(t.elapsed_ms for t in items)
        p95 = elapsed[min(len(elapsed) - 1, int(len(elapsed) * 0.95))]
        routes: dict[str, int] = {}
        agents: dict[str, int] = {}
        kinds: dict[str, list[float]] = {}
        for t in items:
            routes[t.route_level or "-"] = routes.get(t.route_level or "-", 0) + 1
            agents[t.agent_type or "-"] = agents.get(t.agent_type or "-", 0) + 1
            for s in t.spans:
                kinds.setdefault(s.kind, []).append(s.elapsed_ms)
        return {
            "requests": len(items),
            "avg_elapsed_ms": round(sum(elapsed) / len(elapsed), 2),
            "p95_elapsed_ms": round(p95, 2),
            "fallback_rate": round(sum(1 for t in items if t.fallback_used) / len(items), 4),
            "error_rate": round(sum(1 for t in items if t.status == "failed") / len(items), 4),
            "total_tokens": sum(t.total_tokens for t in items),
            "route_distribution": routes,
            "agent_distribution": agents,
            "kind_duration_ms": {k: round(sum(v) / len(v), 2) for k, v in kinds.items()},
        }


trace_store = TraceStore()


def current_trace() -> Trace | None:
    return _current_trace.get()


def start_trace(**meta: Any) -> Trace:
    """开启一条链路 Trace，并把它放进 contextvar（后续节点无需层层传参）。"""
    rid = meta.pop("request_id", None) or new_request_id()
    trace = Trace(request_id=rid, **meta)
    request_id_var.set(rid)
    _current_trace.set(trace)
    _span_stack.set(())
    return trace


def finish_trace(status: str = "success", **meta: Any) -> Trace | None:
    trace = _current_trace.get()
    if trace is None:
        return None
    trace.status = status
    trace.finished_at = time.time()
    for key, value in meta.items():
        if hasattr(trace, key) and value is not None:
            setattr(trace, key, value)
    trace_store.add(trace)
    _current_trace.set(None)
    return trace


def add_tokens(token_in: int = 0, token_out: int = 0) -> None:
    trace = _current_trace.get()
    if trace is not None:
        trace.token_in += token_in
        trace.token_out += token_out


@asynccontextmanager
async def span(name: str, kind: str = "node", **meta: Any):
    """上下文管理器版本的埋点：async with span("node.retrieve", kind="node"): ..."""
    trace = _current_trace.get()
    stack = _span_stack.get()
    span_id = f"sp_{uuid.uuid4().hex[:8]}"
    parent = stack[-1] if stack else None
    record = Span(
        span_id=span_id,
        name=name,
        kind=kind,
        parent=parent,
        depth=len(stack),
        elapsed_ms=0.0,
        meta=dict(meta),
        started_at=time.time(),
    )
    if trace is not None:
        trace.spans.append(record)
    token_before = (trace.token_in, trace.token_out) if trace else (0, 0)
    _span_stack.set(stack + (span_id,))
    t0 = time.perf_counter()
    try:
        yield record
    except Exception as exc:
        record.ok = False
        record.error = repr(exc)
        raise
    finally:
        record.elapsed_ms = (time.perf_counter() - t0) * 1000
        if trace is not None:
            record.token_in = trace.token_in - token_before[0]
            record.token_out = trace.token_out - token_before[1]
        _span_stack.set(stack)


def traced(name: str, kind: str = "node", **meta: Any):
    """装饰器版本的埋点 —— Agent 节点、MCP 调用、Pipeline 串联共用同一个装饰器。"""

    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            async with span(name, kind, **meta):
                return await fn(*args, **kwargs)

        return wrapper

    return deco
