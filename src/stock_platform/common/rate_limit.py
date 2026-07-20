"""인메모리 Rate Limit (단일 인스턴스). STEP62."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class InMemoryRateLimiter:
    """슬라이딩 윈도우 카운터."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def check(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
    ) -> None:
        now = time.monotonic()
        cutoff = now - max(1.0, float(window_seconds))
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= max(1, int(limit)):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="요청이 너무 많습니다. 잠시 후 다시 시도하세요.",
                    headers={"Retry-After": str(int(window_seconds))},
                )
            bucket.append(now)

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()


rate_limiter = InMemoryRateLimiter()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    limit: int,
    window_seconds: float = 60.0,
) -> None:
    key = f"{scope}:{client_ip(request)}"
    rate_limiter.check(
        key,
        limit=limit,
        window_seconds=window_seconds,
    )
