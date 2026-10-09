"""评测接口 —— 一键跑离线评测并返回报告。"""

from __future__ import annotations

from fastapi import APIRouter

from ..evaluation.runner import run_full_evaluation

router = APIRouter(prefix="/api/v1/evaluation", tags=["evaluation"])

_cache: dict = {}


@router.get("/report")
async def report() -> dict:
    if not _cache:
        _cache.update(await run_full_evaluation())
    return _cache


@router.post("/run")
async def run() -> dict:
    """重新跑一遍评测（样本集规模小，耗时 < 1s）。"""
    _cache.clear()
    _cache.update(await run_full_evaluation())
    return _cache
