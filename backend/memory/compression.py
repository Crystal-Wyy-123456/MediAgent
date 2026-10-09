"""上下文压缩策略说明与阈值计算（实际执行在 preconsult 的 save_memory 节点）。"""

from __future__ import annotations

from ..config import settings


def compression_plan(message_count: int) -> dict:
    """滑动窗口（每轮，零成本）+ 摘要压缩（超阈值，语义保留）。"""
    over = message_count > settings.compress_threshold
    return {
        "message_count": message_count,
        "threshold": settings.compress_threshold,
        "keep_recent": settings.keep_recent,
        "strategy": "summary_compression" if over else "sliding_window",
        "description": (
            f"超过 {settings.compress_threshold} 条，靠前消息交给 LLM 生成摘要，仅保留最近 {settings.keep_recent} 条原文"
            if over
            else f"未超 {settings.compress_threshold} 条，仅做确定性裁剪，零 Token 成本"
        ),
    }
