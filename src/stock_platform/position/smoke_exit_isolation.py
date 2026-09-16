"""Smoke 검증 구간용 Position Exit Monitor submission isolation.

평가(trigger detection)는 유지하고, 대상 UBA/symbol에 한해
autonomous EXIT 주문 제출만 억제한다. production exit 보호를 제거하지 않는다.

- UBA/symbol hardcoding 금지
- TTL로 crash 시에도 장기 disable 방지
- context manager로 try/finally 복구
"""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_TTL_SECONDS = 600
MIN_TTL_SECONDS = 30
MAX_TTL_SECONDS = 3600
SUPPRESS_EVENT = "EXIT_TRIGGER_DETECTED_BUT_SUPPRESSED_FOR_SMOKE"
ACQUIRE_EVENT = "SMOKE_EXIT_ISOLATION_ACQUIRED"
RELEASE_EVENT = "SMOKE_EXIT_ISOLATION_RELEASED"


@dataclass(frozen=True, slots=True)
class SmokeExitIsolationLease:
    """단일 smoke isolation lease."""

    lease_id: str
    user_broker_account_id: int
    symbol: str | None
    reason: str
    correlation_id: str | None
    acquired_at: datetime
    expires_at: datetime

    def matches(self, *, user_broker_account_id: int, symbol: str | None) -> bool:
        if int(self.user_broker_account_id) != int(user_broker_account_id):
            return False
        if self.symbol is None:
            return True
        if symbol is None:
            return False
        return str(self.symbol).upper() == str(symbol).upper()

    def is_expired(self, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return moment >= exp

    def as_dict(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "user_broker_account_id": int(self.user_broker_account_id),
            "symbol": self.symbol,
            "reason": self.reason,
            "correlation_id": self.correlation_id,
            "acquired_at": self.acquired_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


class SmokeExitIsolationRegistry:
    """프로세스 내 scoped suppression registry (TTL 포함)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._leases: dict[str, SmokeExitIsolationLease] = {}

    def _purge_expired_locked(self, *, now: datetime) -> None:
        expired = [
            lid
            for lid, lease in self._leases.items()
            if lease.is_expired(now=now)
        ]
        for lid in expired:
            self._leases.pop(lid, None)

    def acquire(
        self,
        *,
        user_broker_account_id: int,
        symbol: str | None = None,
        reason: str = "SMOKE_VALIDATION",
        correlation_id: str | None = None,
        ttl_seconds: int | None = None,
        lease_id: str | None = None,
    ) -> SmokeExitIsolationLease:
        uba = int(user_broker_account_id)
        if uba < 1:
            raise ValueError("user_broker_account_id must be >= 1")
        ttl = int(ttl_seconds if ttl_seconds is not None else _default_ttl_seconds())
        ttl = max(MIN_TTL_SECONDS, min(MAX_TTL_SECONDS, ttl))
        now = datetime.now(timezone.utc)
        sym = str(symbol).upper().strip() if symbol else None
        if sym == "":
            sym = None
        lease = SmokeExitIsolationLease(
            lease_id=str(lease_id or uuid.uuid4().hex),
            user_broker_account_id=uba,
            symbol=sym,
            reason=str(reason or "SMOKE_VALIDATION")[:200],
            correlation_id=(str(correlation_id)[:128] if correlation_id else None),
            acquired_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
        with self._lock:
            self._purge_expired_locked(now=now)
            self._leases[lease.lease_id] = lease
        logger.info(
            ACQUIRE_EVENT,
            lease_id=lease.lease_id,
            user_broker_account_id=uba,
            symbol=sym,
            ttl_seconds=ttl,
            correlation_id=lease.correlation_id,
            reason=lease.reason,
        )
        return lease

    def release(self, lease_id: str) -> bool:
        with self._lock:
            lease = self._leases.pop(str(lease_id), None)
        if lease is None:
            return False
        logger.info(
            RELEASE_EVENT,
            lease_id=lease.lease_id,
            user_broker_account_id=lease.user_broker_account_id,
            symbol=lease.symbol,
            correlation_id=lease.correlation_id,
        )
        return True

    def clear_for_uba(
        self,
        *,
        user_broker_account_id: int,
        symbol: str | None = None,
    ) -> int:
        """대상 UBA(±symbol) lease 전부 해제. 반환=해제 건수."""

        uba = int(user_broker_account_id)
        sym = str(symbol).upper().strip() if symbol else None
        if sym == "":
            sym = None
        removed = 0
        with self._lock:
            self._purge_expired_locked(now=datetime.now(timezone.utc))
            drop: list[str] = []
            for lid, lease in self._leases.items():
                if int(lease.user_broker_account_id) != uba:
                    continue
                if sym is None or lease.symbol is None or lease.symbol == sym:
                    # symbol=None clear → UBA 전체
                    # symbol set → 해당 symbol 또는 UBA-wide lease
                    if sym is None:
                        drop.append(lid)
                    elif lease.symbol is None or lease.symbol == sym:
                        drop.append(lid)
            for lid in drop:
                self._leases.pop(lid, None)
                removed += 1
        return removed

    def find_active(
        self,
        *,
        user_broker_account_id: int,
        symbol: str | None,
    ) -> SmokeExitIsolationLease | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired_locked(now=now)
            for lease in self._leases.values():
                if lease.is_expired(now=now):
                    continue
                if lease.matches(
                    user_broker_account_id=int(user_broker_account_id),
                    symbol=symbol,
                ):
                    return lease
        return None

    def list_active(self) -> list[SmokeExitIsolationLease]:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired_locked(now=now)
            return [
                lease
                for lease in self._leases.values()
                if not lease.is_expired(now=now)
            ]

    def reset_all_for_tests(self) -> None:
        with self._lock:
            self._leases.clear()


_REGISTRY = SmokeExitIsolationRegistry()


def get_smoke_exit_isolation_registry() -> SmokeExitIsolationRegistry:
    return _REGISTRY


def _default_ttl_seconds() -> int:
    try:
        from stock_platform.common.settings import get_settings

        value = int(
            getattr(get_settings(), "smoke_exit_isolation_ttl_seconds", DEFAULT_TTL_SECONDS)
        )
        return max(MIN_TTL_SECONDS, min(MAX_TTL_SECONDS, value))
    except Exception:  # noqa: BLE001
        return DEFAULT_TTL_SECONDS


def metadata_requests_smoke_exit_isolation(metadata: dict[str, Any] | None) -> bool:
    """OES/smoke metadata가 isolation 자동 acquire를 요청하는지."""

    meta = metadata if isinstance(metadata, dict) else {}
    if meta.get("smoke_exit_isolation") is True:
        return True
    if str(meta.get("smoke_exit_isolation") or "").strip().lower() in {"1", "true", "yes"}:
        return True
    reason = str(meta.get("reason") or "").upper()
    if "SMOKE" in reason:
        return True
    source = str(meta.get("source") or "").upper()
    if "SMOKE" in source:
        return True
    return False


def acquire_smoke_exit_isolation(
    *,
    user_broker_account_id: int,
    symbol: str | None = None,
    reason: str = "SMOKE_VALIDATION",
    correlation_id: str | None = None,
    ttl_seconds: int | None = None,
) -> SmokeExitIsolationLease:
    return _REGISTRY.acquire(
        user_broker_account_id=user_broker_account_id,
        symbol=symbol,
        reason=reason,
        correlation_id=correlation_id,
        ttl_seconds=ttl_seconds,
    )


def release_smoke_exit_isolation(lease_id: str) -> bool:
    return _REGISTRY.release(lease_id)


def is_exit_submission_suppressed_for_smoke(
    *,
    user_broker_account_id: int | None,
    symbol: str | None,
) -> SmokeExitIsolationLease | None:
    if user_broker_account_id is None:
        return None
    return _REGISTRY.find_active(
        user_broker_account_id=int(user_broker_account_id),
        symbol=symbol,
    )


@contextmanager
def smoke_exit_isolation(
    *,
    user_broker_account_id: int,
    symbol: str | None = None,
    reason: str = "SMOKE_VALIDATION",
    correlation_id: str | None = None,
    ttl_seconds: int | None = None,
) -> Iterator[SmokeExitIsolationLease]:
    """성공/실패와 무관하게 lease를 해제하는 isolation boundary."""

    lease = acquire_smoke_exit_isolation(
        user_broker_account_id=user_broker_account_id,
        symbol=symbol,
        reason=reason,
        correlation_id=correlation_id,
        ttl_seconds=ttl_seconds,
    )
    try:
        yield lease
    finally:
        release_smoke_exit_isolation(lease.lease_id)


def maybe_acquire_from_order_metadata(
    *,
    user_broker_account_id: int | None,
    symbol: str | None,
    metadata: dict[str, Any] | None,
    environment: str | None = None,
) -> SmokeExitIsolationLease | None:
    """LIVE smoke 주문 생성 시 isolation을 자동 acquire."""

    if user_broker_account_id is None:
        return None
    if str(environment or "").upper() not in {"", "LIVE"}:
        # PAPER는 exit monitor LIVE 경로와 무관 — LIVE만
        if str(environment or "").upper() == "PAPER":
            return None
    if not metadata_requests_smoke_exit_isolation(metadata):
        return None
    meta = metadata if isinstance(metadata, dict) else {}
    ttl_raw = meta.get("smoke_exit_isolation_ttl_seconds")
    ttl = None
    if ttl_raw is not None:
        try:
            ttl = int(ttl_raw)
        except (TypeError, ValueError):
            ttl = None
    return acquire_smoke_exit_isolation(
        user_broker_account_id=int(user_broker_account_id),
        symbol=symbol,
        reason=str(meta.get("reason") or "SMOKE_ORDER_METADATA")[:200],
        correlation_id=str(meta.get("correlation_id") or "")[:128] or None,
        ttl_seconds=ttl,
    )
