"""第一层降级兜底：自动重试（指数退避）。

触发条件：网络抖动 / LLM 超时 / 瞬时 5xx。间隔 1s -> 3s，最多 2 次。
"""

from __future__ import annotations

import asyncio
import functools
import random
from typing import Awaitable, Callable, TypeVar

from ..config import settings
from ..observability.logger import log_event

T = TypeVar("T")


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int | None = None,
    base_delay: float | None = None,
    label: str = "call",
) -> T:
    max_retries = settings.retry_max if max_retries is None else max_retries
    base_delay = settings.retry_base_delay if base_delay is None else base_delay
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= max_retries:
                break
            delay = base_delay * (3**attempt) + random.uniform(0, 0.05)
            log_event("retry", label=label, attempt=attempt + 1, delay=round(delay, 2), error=repr(exc))
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


def retryable(max_retries: int | None = None, label: str | None = None):
    """装饰器写法：@retryable(label="llm.generate")"""

    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            return await with_retry(
                lambda: fn(*args, **kwargs),
                max_retries=max_retries,
                label=label or fn.__name__,
            )

        return wrapper

    return deco
