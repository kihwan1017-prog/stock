"""프로세스 내 TTL 캐시 — API 계약 변경 없이 반복 I/O 완화."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, TypeVar


T = TypeVar("T")


class TtlCache:
    """단순 thread-safe TTL 캐시."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < now:
                del self._items[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        ttl = max(0.1, float(ttl_seconds))
        with self._lock:
            self._items[key] = (time.monotonic() + ttl, value)

    def get_or_set(
        self,
        key: str,
        factory: Callable[[], T],
        *,
        ttl_seconds: float,
    ) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        value = factory()
        self.set(key, value, ttl_seconds)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


# Ollama /api/tags 등 공유 캐시
process_ttl_cache = TtlCache()
