from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class IdempotencyEntry(Generic[T]):
    key: str
    value: T
    created_at: datetime


class InMemoryIdempotencyStore(Generic[T]):
    def __init__(self) -> None:
        self._entries: dict[str, IdempotencyEntry[T]] = {}
        self._lock = RLock()

    def get(self, key: str) -> T | None:
        with self._lock:
            entry = self._entries.get(key)
            return None if entry is None else entry.value

    def execute_once(
        self,
        *,
        key: str,
        operation: Callable[[], T],
    ) -> T:
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                return existing.value

            value = operation()
            self._entries[key] = IdempotencyEntry(
                key=key,
                value=value,
                created_at=datetime.now(timezone.utc),
            )
            return value
