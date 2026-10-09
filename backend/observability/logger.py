"""结构化 JSON 日志 —— 单行一条，便于落表与检索。

日志里自动带上 request_id，一条 SQL 就能捞出某个请求的完整轨迹。
"""

from __future__ import annotations

import json
import logging
import sys

from .trace import request_id_var


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        for key in ("span", "kind", "elapsed_ms", "ok", "error", "agent", "tool"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str = "mediagent") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_event(event: str, **fields) -> None:
    """结构化事件日志。"""
    get_logger().info(event, extra={"extra_fields": fields})
