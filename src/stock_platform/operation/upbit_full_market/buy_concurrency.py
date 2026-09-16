"""UPBIT AUTO BUY 제한 병렬(V1) — max concurrent entries/executor/submit = 2.

SoT:
  - pending 한도: portfolio_max_pending_entries (DB policy), V1 코드 상한 2
  - executor/submit: Settings (기본 1, 상한 2)

잘못된 값(0/음수/>2) → 보수적 clamp=1.
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# V1 hard ceiling — 절대 초과 금지
V1_MAX_CONCURRENT_ENTRIES = 2
V1_MAX_EXECUTOR_CONCURRENCY = 2
V1_MAX_ORDER_SUBMIT_CONCURRENCY = 2

_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def clamp_concurrency_v1(raw: Any, *, hard_max: int = V1_MAX_CONCURRENT_ENTRIES) -> int:
    """유효 범위 1..hard_max. 그 외는 fail-closed → 1."""

    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    if value < 1 or value > int(hard_max):
        return 1
    return value


def resolve_max_concurrent_entries(policy_or_value: Any) -> int:
    """DB policy.portfolio_max_pending_entries → V1 clamp."""

    if hasattr(policy_or_value, "portfolio_max_pending_entries"):
        raw = getattr(policy_or_value, "portfolio_max_pending_entries", 1)
    else:
        raw = policy_or_value
    return clamp_concurrency_v1(raw, hard_max=V1_MAX_CONCURRENT_ENTRIES)


def resolve_executor_concurrency(settings: Any | None = None) -> int:
    if settings is None:
        from stock_platform.common.settings import get_settings

        settings = get_settings()
    raw = getattr(settings, "upbit_buy_executor_concurrency", 1)
    return clamp_concurrency_v1(raw, hard_max=V1_MAX_EXECUTOR_CONCURRENCY)


def resolve_order_submit_concurrency(settings: Any | None = None) -> int:
    if settings is None:
        from stock_platform.common.settings import get_settings

        settings = get_settings()
    raw = getattr(settings, "upbit_buy_order_submit_concurrency", 1)
    return clamp_concurrency_v1(raw, hard_max=V1_MAX_ORDER_SUBMIT_CONCURRENCY)


def _admission_lock_key(uba_id: int) -> int:
    raw = f"upbit-buy-admission|{int(uba_id)}".encode()
    digest = hashlib.blake2b(raw, digest_size=8).digest()
    return int.from_bytes(digest, "big") & 0x7FFFFFFFFFFFFFFF


def _process_admission_lock(uba_id: int) -> threading.RLock:
    key = f"upbit-buy-admission|{int(uba_id)}"
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[key] = lock
        return lock


def acquire_buy_admission_xact_lock(
    session: Session,
    *,
    user_broker_account_id: int,
) -> threading.RLock:
    """짧은 admission critical section용 잠금.

    PostgreSQL: pg_advisory_xact_lock (트랜잭션 종료까지)
    전 환경: 프로세스 RLock 반환 — 호출자가 with 로 감싼다.
    """

    uba_id = int(user_broker_account_id)
    lock = _process_admission_lock(uba_id)
    try:
        bind = session.get_bind()
        dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "")
        if dialect == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(:k)"),
                {"k": _admission_lock_key(uba_id)},
            )
    except Exception:  # noqa: BLE001 — fail-open to process lock only
        pass
    return lock
