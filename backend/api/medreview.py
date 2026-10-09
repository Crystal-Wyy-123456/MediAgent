"""病历质控接口 —— 提交 / 查询 / 逐条采纳。"""

from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..agents.medreview.rules import RULES
from ..infra.db import db
from ..orchestrator.core import orchestrator
from ..orchestrator.schema import AgentRequest, AgentType
from ..rag.loader import load_bytes
from .deps import RequestContext, get_request_context

router = APIRouter(prefix="/api/v1/medreview", tags=["medreview"])


class SubmitRequest(BaseModel):
    text: str
    title: str = ""
    session_id: str = ""


class IssuePatch(BaseModel):
    accepted: bool
    comment: str = ""


async def _run_review(text: str, ctx: RequestContext, title: str = "") -> dict:
    if not text.strip():
        raise HTTPException(status_code=400, detail="病历内容为空")
    response = await orchestrator.handle(
        AgentRequest(
            agent_type=AgentType.MEDREVIEW,
            query=text,
            session_id=f"qc_{uuid.uuid4().hex[:10]}",
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            user_role=ctx.user_role,  # type: ignore[arg-type]
        )
    )
    structured = response.structured or {}
    if title:
        await db.execute(
            "UPDATE record_review SET patient_name = ? WHERE review_id = ?",
            (structured.get("structured_record", {}).get("patient_name") or title, structured.get("review_id")),
        )
    structured["trace_id"] = response.trace_id
    structured["elapsed_ms"] = response.latency_ms
    structured["tokens"] = response.tokens
    return structured


@router.post("/submit")
async def submit(body: SubmitRequest, ctx: RequestContext = Depends(get_request_context)) -> dict:
    return await _run_review(body.text, ctx, body.title)


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    ctx: RequestContext = Depends(get_request_context),
) -> dict:
    """上传 PDF / DOCX / TXT 病历文件。"""
    data = await file.read()
    try:
        text = load_bytes(file.filename or "record.txt", data)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _run_review(text, ctx, title=file.filename or "")


@router.get("")
async def list_reviews(limit: int = 20, ctx: RequestContext = Depends(get_request_context)) -> dict:
    rows = await db.fetch_all(
        """SELECT review_id, patient_name, overall_score, grade, status, elapsed_ms, created_at
             FROM record_review WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?""",
        (ctx.tenant_id, limit),
    )
    for row in rows:
        issues = await db.fetch_all(
            "SELECT severity FROM review_issue WHERE review_id = ?", (row["review_id"],)
        )
        row["issue_count"] = len(issues)
        row["error_count"] = sum(1 for i in issues if i["severity"] == "error")
    return {"items": rows, "total": len(rows)}


@router.get("/rules")
async def list_rules() -> dict:
    return {
        "items": [
            {
                "rule_id": r.id,
                "rule_name": r.name,
                "level": r.level,
                "weight": r.weight,
                "location": r.location,
                "suggestion": r.suggestion,
            }
            for r in RULES
        ],
        "note": "规则表由配置驱动，按租户加载不同规则集，新增规则不改代码",
    }


@router.get("/{review_id}")
async def get_review(review_id: str, ctx: RequestContext = Depends(get_request_context)) -> dict:
    row = await db.fetch_one(
        "SELECT * FROM record_review WHERE review_id = ? AND tenant_id = ?", (review_id, ctx.tenant_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="质控记录不存在")
    issues = await db.fetch_all(
        "SELECT * FROM review_issue WHERE review_id = ? ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END",
        (review_id,),
    )
    return {
        "review_id": row["review_id"],
        "patient_name": row["patient_name"],
        "overall_score": row["overall_score"],
        "grade": row["grade"],
        "status": row["status"],
        "elapsed_ms": row["elapsed_ms"],
        "created_at": row["created_at"],
        "structured_record": json.loads(row["structured_record"]),
        "dimension_results": json.loads(row["dimension_results"]),
        "rule_results": json.loads(row["rule_results"]),
        "cross_doc_results": json.loads(row["cross_doc_results"] or "[]"),
        "issues": issues,
    }


@router.patch("/{review_id}/issues/{issue_id}")
async def patch_issue(
    review_id: str,
    issue_id: str,
    body: IssuePatch,
    ctx: RequestContext = Depends(get_request_context),
) -> dict:
    del ctx
    await db.execute(
        "UPDATE review_issue SET accepted = ? WHERE issue_id = ?",
        (1 if body.accepted else 0, f"{review_id}:{issue_id}"),
    )
    row = await db.fetch_one("SELECT issue_id, accepted FROM review_issue WHERE issue_id = ?", (f"{review_id}:{issue_id}",))
    if not row:
        raise HTTPException(status_code=404, detail="问题条目不存在")
    return {"issue_id": issue_id, "accepted": bool(row["accepted"]), "updated_at": time.time()}
