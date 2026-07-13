import asyncio
import time
from collections import deque


class AsyncSlidingWindowRateLimiter:
    """Simple process-local sliding-window limiter."""

    def __init__(
        self,
        max_requests: int,
        period_seconds: float = 1.0,
    ) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be greater than zero")

        self._max_requests = max_requests
        self._period_seconds = period_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()

                while (
                    self._timestamps
                    and now - self._timestamps[0] >= self._period_seconds
                ):
                    self._timestamps.popleft()

                if len(self._timestamps) < self._max_requests:
                    self._timestamps.append(now)
                    return

                wait_seconds = (
                    self._period_seconds
                    - (now - self._timestamps[0])
                )

            await asyncio.sleep(max(wait_seconds, 0.001))
