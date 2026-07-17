from __future__ import annotations

from collections import deque
from threading import Lock
from time import monotonic, sleep


class SlidingWindowRateLimiter:
    def __init__(
        self,
        *,
        max_calls: int,
        period_seconds: float,
    ) -> None:
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        if period_seconds <= 0:
            raise ValueError(
                "period_seconds must be positive"
            )

        self._max_calls = max_calls
        self._period = period_seconds
        self._calls: deque[float] = deque()
        self._lock = Lock()

    def acquire(self) -> None:
        while True:
            wait_seconds = 0.0

            with self._lock:
                now = monotonic()
                boundary = now - self._period

                while (
                    self._calls
                    and self._calls[0] <= boundary
                ):
                    self._calls.popleft()

                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return

                wait_seconds = max(
                    0.001,
                    self._period
                    - (now - self._calls[0]),
                )

            sleep(wait_seconds)


class KiwoomRateLimiters:
    def __init__(
        self,
        *,
        order_calls_per_second: int = 5,
        inquiry_calls_per_second: int = 5,
    ) -> None:
        self.order = SlidingWindowRateLimiter(
            max_calls=order_calls_per_second,
            period_seconds=1.0,
        )
        self.inquiry = SlidingWindowRateLimiter(
            max_calls=inquiry_calls_per_second,
            period_seconds=1.0,
        )
