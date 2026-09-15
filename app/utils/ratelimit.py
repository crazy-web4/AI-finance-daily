"""
限流检测与重试（建议 #12 · T-D12）
=================================================
识别 429 / 额度耗尽 / rate limit 错误，按 Retry-After 或指数退避重试；
超过次数后抛出 :class:`RateLimitExhausted`，交由降级路径（fallback.py）处理。

``sleep`` 可注入，便于单测不真正等待。
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_RATE_PATTERNS = re.compile(
    r"(rate[\s_-]?limit|too many requests|429|quota|insufficient.?quota|额度|限流|请求过于频繁)",
    re.IGNORECASE,
)


class RateLimitExhausted(RuntimeError):
    """重试次数耗尽仍被限流。"""


@dataclass
class RetryPolicy:
    max_retries: int = 3          # 限流后的额外重试次数
    base_delay: float = 5.0       # 无 Retry-After 时的基础退避
    max_delay: float = 60.0       # 单次等待上限
    default_retry_after: float = 60.0
    attempts: int = field(default=0)

    def backoff(self, attempt: int) -> float:
        return min(self.base_delay * (2 ** attempt), self.max_delay)


def is_rate_limit(exc: BaseException | None) -> bool:
    """判断异常是否为限流/额度问题。"""
    if exc is None:
        return False
    # openai SDK / httpx 风格的状态码
    code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if code == 429:
        return True
    msg = str(exc)
    if _RATE_PATTERNS.search(msg):
        return True
    # 递归看 cause
    cause = getattr(exc, "__cause__", None)
    if cause is not None and cause is not exc:
        return is_rate_limit(cause)
    return False


def retry_after_seconds(exc: BaseException, default: float | None = None) -> float | None:
    """从异常中解析 Retry-After（秒）。"""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None)
    if headers is not None:
        try:
            val = headers.get("retry-after") or headers.get("Retry-After")
            if val is not None:
                return float(val)
        except (TypeError, ValueError):
            pass
    # openai SDK 可能把 response 藏在 exc.response
    for attr in ("response",):
        obj = getattr(exc, attr, None)
        # httpx.Response.headers
    return default


def call_with_retry(
    fn: Callable[..., T],
    *args: Any,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    is_rate: Callable[[BaseException], bool] = is_rate_limit,
    **kwargs: Any,
) -> T:
    """
    同步调用 ``fn``，遇到限流按策略重试。

    非限流异常立即抛出；限流重试耗尽抛 :class:`RateLimitExhausted`。
    """
    policy = policy or RetryPolicy()
    last: BaseException | None = None
    for attempt in range(policy.max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 需要分类后再决定抛或重试
            last = exc
            if not is_rate(exc):
                raise
            if attempt >= policy.max_retries:
                break
            wait = retry_after_seconds(exc) or policy.backoff(attempt)
            wait = min(wait, policy.max_delay)
            sleep(wait)
            policy.attempts += 1
    raise RateLimitExhausted(f"限流重试 {policy.max_retries} 次后仍失败: {last}") from last


async def acall_with_retry(
    fn: Callable[..., Any],
    *args: Any,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], Any] | None = None,
    is_rate: Callable[[BaseException], bool] = is_rate_limit,
    **kwargs: Any,
) -> Any:
    """异步版本：``fn`` 可以是协程函数或返回 awaitable。"""
    policy = policy or RetryPolicy()
    async_sleep = sleep or asyncio.sleep
    last: BaseException | None = None
    for attempt in range(policy.max_retries + 1):
        try:
            result = fn(*args, **kwargs)
            if asyncio.iscoroutine(result) or hasattr(result, "__await__"):
                result = await result
            return result
        except Exception as exc:  # noqa: BLE001
            last = exc
            if not is_rate(exc):
                raise
            if attempt >= policy.max_retries:
                break
            wait = retry_after_seconds(exc) or policy.backoff(attempt)
            wait = min(wait, policy.max_delay)
            await async_sleep(wait)
            policy.attempts += 1
    raise RateLimitExhausted(f"限流重试 {policy.max_retries} 次后仍失败: {last}") from last
