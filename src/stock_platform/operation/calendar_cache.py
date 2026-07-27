"""STEP 8-5-11 — KRX Calendar in-process cache (no Redis).

TTL 기본 2초. Revision 변경·Apply 후 명시적 invalidate.
다중 인스턴스 최대 지연 ≈ TTL (문서화).
"""

from __future__ import annotations

import threading
import time as time_mod
from datetime import date
from typing import Any

_lock = threading.RLock()
_store: dict[tuple[str, date], tuple[float, int, Any]] = {}
DEFAULT_TTL_SECONDS = 2.0


def cache_get(
    *,
    exchange_code: str,
    calendar_date: date,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> tuple[int, Any] | None:
    key = (exchange_code.upper(), calendar_date)
    now = time_mod.monotonic()
    with _lock:
        item = _store.get(key)
        if item is None:
            return None
        expires_at, revision, payload = item
        if now > expires_at:
            _store.pop(key, None)
            return None
        if ttl_seconds <= 0:
            return None
        return revision, payload


def cache_set(
    *,
    exchange_code: str,
    calendar_date: date,
    revision: int,
    payload: Any,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> None:
    key = (exchange_code.upper(), calendar_date)
    expires_at = time_mod.monotonic() + max(0.0, float(ttl_seconds))
    with _lock:
        _store[key] = (expires_at, int(revision), payload)


def invalidate_calendar_cache(
    *,
    exchange_code: str | None = None,
    calendar_date: date | None = None,
) -> None:
    with _lock:
        if exchange_code is None and calendar_date is None:
            _store.clear()
            return
        if exchange_code is not None and calendar_date is not None:
            _store.pop((exchange_code.upper(), calendar_date), None)
            return
        dead = [
            k
            for k in _store
            if (
                exchange_code is None
                or k[0] == exchange_code.upper()
            )
            and (calendar_date is None or k[1] == calendar_date)
        ]
        for k in dead:
            _store.pop(k, None)


def cache_revision(
    *, exchange_code: str, calendar_date: date
) -> int | None:
    hit = cache_get(
        exchange_code=exchange_code, calendar_date=calendar_date
    )
    if hit is None:
        return None
    return int(hit[0])
