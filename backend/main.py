"""FastAPI 入口 —— 网关层：认证 · 租户解析 · SSE 连接管理 · 静态资源。"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import admin, auth, chat, evaluation, library, medqa, medreview, pipeline, preconsult
from .config import BASE_DIR, settings
from .infra.db import db
from .observability.logger import get_logger, log_event
from .observability.trace import Trace, trace_store
from .rag.knowledge_base import kb_stats
from .tools.registry import mcp_registry

logger = get_logger()
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


async def _write_trace(trace: Trace) -> None:
    try:
        await db.execute(
            """INSERT OR REPLACE INTO agent_trace
               (request_id, tenant_id, user_id, session_id, agent_type, route_level, status, fallback_used,
                token_in, token_out, elapsed_ms, span_count, query, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trace.request_id,
                trace.tenant_id,
                trace.user_id,
                trace.session_id,
                trace.agent_type,
                trace.route_level,
                trace.status,
                1 if trace.fallback_used else 0,
                trace.token_in,
                trace.token_out,
                trace.elapsed_ms,
                len(trace.spans),
                trace.query[:200],
                trace.started_at,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - 观测失败绝不影响主流程
        log_event("trace_persist_failed", error=repr(exc))


def _trace_sink(trace: Trace) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_write_trace(trace))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    trace_store.bind_sink(_trace_sink)
    await mcp_registry.discover()
    log_event(
        "app_started",
        app=settings.app_name,
        version=settings.app_version,
        llm_provider=settings.llm_provider,
        mcp_transport=mcp_registry.transport,
        kb=kb_stats(),
    )
    yield
    db.close()
    log_event("app_stopped")


app = FastAPI(
    title="MediAgent API",
    version=settings.app_version,
    description="面向医疗机构的智能诊疗协作多 Agent 平台：MedQA / MedReview / PreConsult + Orchestrator 编排层",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, chat, medqa, medreview, preconsult, pipeline, admin, library, evaluation):
    app.include_router(module.router)


@app.get("/api/v1/health", tags=["system"])
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "llm_provider": settings.llm_provider,
        "mcp_tools": len(mcp_registry.list_tools()),
        "kb": kb_stats(),
        "timestamp": time.time(),
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):  # noqa: ANN001
    logger.exception("unhandled_exception", extra={"extra_fields": {"path": str(request.url)}})
    return JSONResponse(status_code=500, content={"detail": "系统处理遇到问题，请稍后重试。"})


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa_fallback(path: str) -> FileResponse:
        candidate = FRONTEND_DIST / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

else:

    @app.get("/", include_in_schema=False)
    async def api_root() -> dict:
        return {
            "app": settings.app_name,
            "docs": "/docs",
            "hint": "前端未构建：请在 frontend 目录执行 npm install && npm run dev（开发）或 npm run build（生产）",
            "endpoints": [r.path for r in app.routes if getattr(r, "path", "").startswith("/api")],
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=settings.debug)
