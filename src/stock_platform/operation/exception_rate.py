"""간단 예외율 카운터 — 모니터링용 (STEP61)."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


class ExceptionRateTracker:
    """최근 윈도우 내 unhandled/5xx 계열 이벤트 수."""

    def __init__(self, *, window_seconds: float = 300.0) -> None:
        self._window = max(30.0, float(window_seconds))
        self._lock = threading.Lock()
        self._events: deque[float] = deque()

    def record(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._events.append(now)
            self._trim(now)

    def _trim(self, now: float) -> None:
        cutoff = now - self._window
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            self._trim(now)
            count = len(self._events)
        return {
            "window_seconds": self._window,
            "exception_count": count,
            "rate_per_minute": round(
                count / (self._window / 60.0), 3
            ),
        }


exception_rate_tracker = ExceptionRateTracker()
