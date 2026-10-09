"""管理后台接口 —— 指标大盘 / Trace 检索 / MCP 工具 / Agent 拓扑 / 评测报告。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..agents.medqa.graph import MEDQA_TOPOLOGY
from ..agents.medreview.graph import MEDREVIEW_TOPOLOGY
from ..agents.preconsult.graph import PRECONSULT_TOPOLOGY
from ..config import settings
from ..infra.db import db
from ..infra.llm_factory import llm_factory
from ..infra.milvus import collection_stats
from ..memory.checkpointer import memory_info
from ..observability.logger import get_logger
from ..observability.trace import trace_store
from ..orchestrator.core import orchestrator
from ..orchestrator.pipeline import pipeline_topology
from ..tools.registry import mcp_registry
from .deps import RequestContext, get_request_context

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
logger = get_logger()


@router.get("/overview")
async def overview(ctx: RequestContext = Depends(get_request_context)) -> dict:
    stats = trace_store.stats()
    reviews = await db.fetch_all(
        "SELECT overall_score, grade, elapsed_ms FROM record_review WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 50",
        (ctx.tenant_id,),
    )
    sessions = await db.fetch_all(
        "SELECT current_stage, handover FROM preconsult_record WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 50",
        (ctx.tenant_id,),
    )
    issues = await db.fetch_all(
        """SELECT i.severity, i.dimension FROM review_issue i
             JOIN record_review r ON r.review_id = i.review_id
            WHERE r.tenant_id = ?""",
        (ctx.tenant_id,),
    )
    dimension_counter: dict[str, int] = {}
    for issue in issues:
        dimension_counter[issue["dimension"]] = dimension_counter.get(issue["dimension"], 0) + 1

    return {
        "runtime": {
            **stats,
            "llm": llm_factory.describe(),
            "knowledge_base": collection_stats(),
            "routing": orchestrator.router.stats(),
            "memory": memory_info(),
        },
        "quality": {
            "reviews": len(reviews),
            "avg_score": round(sum(r["overall_score"] or 0 for r in reviews) / len(reviews), 2) if reviews else None,
            "avg_elapsed_ms": round(sum(r["elapsed_ms"] or 0 for r in reviews) / len(reviews), 2) if reviews else None,
            "issue_by_dimension": dimension_counter,
            "issue_total": len(issues),
            "error_ratio": round(sum(1 for i in issues if i["severity"] == "error") / len(issues), 4) if issues else 0,
        },
        "preconsult": {
            "sessions": len(sessions),
            "handover_count": sum(1 for s in sessions if s["handover"]),
            "stage_distribution": _counter(s["current_stage"] for s in sessions),
        },
    }


def _counter(values) -> dict:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out


@router.get("/traces")
async def traces(limit: int = 50, only_failed: bool = False) -> dict:
    items = trace_store.list(limit * 3 if only_failed else limit)
    if only_failed:
        items = [t for t in items if t.status != "success"][:limit]
    return {"items": [t.to_dict(with_spans=False) for t in items], "total": len(items)}


@router.get("/traces/{request_id}")
async def trace_detail(request_id: str) -> dict:
    trace = trace_store.get(request_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace 不存在（可能已被环形缓冲淘汰）")
    return trace.to_dict(with_spans=True)


@router.get("/mcp/tools")
async def mcp_tools() -> dict:
    if not mcp_registry._discovered:  # noqa: SLF001
        await mcp_registry.discover()
    return {
        "transport": mcp_registry.transport,
        "tools": mcp_registry.list_tools(),
        "note": "工具以 MCP Server 暴露，Agent 按名字调用；transport 可插拔（inproc / stdio）",
    }


@router.post("/mcp/call")
async def mcp_call(body: dict) -> dict:
    tool = body.get("tool")
    args = body.get("args") or {}
    if not tool:
        raise HTTPException(status_code=400, detail="缺少 tool 参数")
    try:
        result = await mcp_registry.call(tool, args)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tool": tool, "args": args, "result": result}


@router.get("/agents/topology")
async def agent_topology() -> dict:
    return {
        "agents": [MEDQA_TOPOLOGY, MEDREVIEW_TOPOLOGY, PRECONSULT_TOPOLOGY],
        "pipelines": pipeline_topology(),
        "runtime": orchestrator.graphs.status(),
    }


@router.get("/system")
async def system_info() -> dict:
    return {
        "app": {"name": settings.app_name, "version": settings.app_version},
        "llm": llm_factory.describe(),
        "retrieval": {
            "embedding_provider": settings.embedding_provider,
            "rerank_provider": settings.rerank_provider,
            "top_n": settings.retrieval_top_n,
            "top_k": settings.retrieval_top_k,
            "weights": {"dense": settings.dense_weight, "sparse": settings.sparse_weight},
            "gates": {"generate": settings.confidence_generate, "refuse": settings.confidence_refuse, "min_docs": settings.min_docs},
            "collection": collection_stats(),
        },
        "memory": memory_info(),
        "observability": {
            "trace_sinks": ["当前进程内存", "本地数据库"],
            "sample_rate": settings.trace_success_sample_rate,
            "request_id_header": "X-Request-Id",
        },
        "mcp": {"transport": settings.mcp_transport, "tools": len(mcp_registry.list_tools())},
        "principles": [
            "用确定性的手段解决确定性的问题",
            "每一层只引入它真正需要的复杂度",
            "上量之前，中间件是负债而不是资产",
            "任何情况下都向用户返回可读的处理结果，不直接暴露系统异常",
        ],
    }
