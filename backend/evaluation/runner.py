"""评测执行器 —— 检索质量 / Agent 能力 / 医疗安全三层离线评测。"""

from __future__ import annotations

import time

from ..agents.preconsult.red_flags import detect_red_flags, needs_llm_double_check
from ..infra.local_engine import run_structured
from ..rag.retriever import get_retriever
from .datasets import RED_FLAG_SET, REFUSE_SET, RETRIEVAL_SET, ROUTING_SET, TARGETS


async def eval_retrieval(top_k: int = 3) -> dict:
    retriever = get_retriever()
    hit = 0
    reciprocal = 0.0
    rows = []
    t0 = time.perf_counter()
    for case in RETRIEVAL_SET:
        result = await retriever.search(case["query"], top_k=top_k)
        ids = [d["chunk_id"] for d in result["docs"]]
        rank = next((i + 1 for i, cid in enumerate(ids) if cid in case["expected"]), 0)
        hit += 1 if rank else 0
        reciprocal += (1 / rank) if rank else 0.0
        rows.append({"query": case["query"], "top": ids[:3], "expected": case["expected"], "rank": rank, "confidence": result["confidence"]})
    total = len(RETRIEVAL_SET)
    return {
        "metric": f"Recall@{top_k}",
        "value": round(hit / total, 4),
        "target": TARGETS["recall_at_3"],
        "mrr": round(reciprocal / total, 4),
        "cases": rows,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
        "pass": hit / total >= TARGETS["recall_at_3"],
    }


async def eval_routing() -> dict:
    correct = 0
    rows = []
    for case in ROUTING_SET:
        decision = run_structured("RouteDecision", {"query": case["query"]})
        ok = decision["agent_type"] == case["expected"]
        correct += 1 if ok else 0
        rows.append({"query": case["query"], "expected": case["expected"], "got": decision["agent_type"], "ok": ok})
    total = len(ROUTING_SET)
    return {
        "metric": "意图路由准确率",
        "value": round(correct / total, 4),
        "target": TARGETS["routing_accuracy"],
        "cases": rows,
        "pass": correct / total >= TARGETS["routing_accuracy"],
    }


async def eval_safety() -> dict:
    retriever = get_retriever()
    correct = 0
    rows = []
    for case in REFUSE_SET:
        result = await retriever.search(case["query"], top_k=3)
        should_refuse = result["confidence"] < 0.62
        ok = should_refuse == case["should_refuse"]
        correct += 1 if ok else 0
        rows.append({"query": case["query"], "confidence": result["confidence"], "expected_refuse": case["should_refuse"], "gate_refuse": should_refuse, "ok": ok})

    red_flag_hit = 0
    red_flag_rows = []
    for case in RED_FLAG_SET:
        hits = detect_red_flags(case["text"])
        if not hits:
            from ..infra.local_engine import run_structured as engine

            judgement = engine("RedFlagJudgement", {"text": case["text"]}) if needs_llm_double_check(case["text"], hits) else {"hit": False}
            hit = bool(judgement.get("hit"))
        else:
            hit = True
        ok = hit == case["should_hit"]
        red_flag_hit += 1 if ok else 0
        red_flag_rows.append({"text": case["text"], "expected": case["should_hit"], "hit": hit, "ok": ok})

    total = len(REFUSE_SET)
    red_total = len(RED_FLAG_SET)
    return {
        "metric": "拒答准确率 / 红旗症状识别准确率",
        "value": round(correct / total, 4),
        "red_flag_value": round(red_flag_hit / red_total, 4),
        "target": {"refuse": TARGETS["refuse_accuracy"], "red_flag": TARGETS["red_flag_recall"]},
        "cases": rows,
        "red_flag_cases": red_flag_rows,
        "pass": correct / total >= TARGETS["refuse_accuracy"] and red_flag_hit / red_total >= TARGETS["red_flag_recall"],
    }


async def run_full_evaluation() -> dict:
    t0 = time.perf_counter()
    retrieval = await eval_retrieval()
    routing = await eval_routing()
    safety = await eval_safety()
    return {
        "datasets": {
            "retrieval": len(RETRIEVAL_SET),
            "routing": len(ROUTING_SET),
            "refuse": len(REFUSE_SET),
            "red_flag": len(RED_FLAG_SET),
            "note": "当前为专家抽检样本集，正在扩充至 300+ 条专家标注 QA 与安全专项集",
        },
        "retrieval": retrieval,
        "agent": routing,
        "safety": safety,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
        "all_pass": retrieval["pass"] and routing["pass"] and safety["pass"],
        "targets": TARGETS,
    }
