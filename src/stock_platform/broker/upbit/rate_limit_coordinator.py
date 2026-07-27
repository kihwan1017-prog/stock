"""STEP 8-5-8 — Upbit Rate Limit Coordinator (memory + PG cooldown)."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from stock_platform.broker.upbit.exceptions import (
    UpbitBanOrBlockError,
    UpbitRateLimitError,
)
from stock_platform.broker.upbit.rate_limit_constants import (
    SCOPE_PUBLIC,
    SCOPE_UBA,
    UpbitRateLimitStatus,
)
from stock_platform.broker.upbit.rate_limit_entities import (
    UpbitApiRateLimitStateEntity,
)
from stock_platform.broker.upbit.rate_limit_header_parser import (
    UpbitRateLimitSnapshot,
)
from stock_platform.broker.recovery_instance_id import (
    get_recovery_instance_identity,
)

logger = logging.getLogger(__name__)


@dataclass
class _MemoryBucket:
    cooldown_until: float = 0.0
    blocked_until: float = 0.0
    remaining_second: int | None = None
    remaining_minute: int | None = None
    last_http_status: int | None = None
    consecutive: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class UpbitRateLimitCoordinator:
    """
    프로세스 내부 초단기 throttle + 긴 Cooldown/418은 PostgreSQL 공유.

    USER A의 429가 USER B를 막지 않도록 UBA scope로 격리.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        persist_cooldown_seconds: float = 10.0,
        default_418_block_seconds: float = 600.0,
        instance_id: str | None = None,
    ) -> None:
        self._enabled = enabled
        self._persist_seconds = float(persist_cooldown_seconds)
        self._block_418 = float(default_418_block_seconds)
        self._instance_id = (
            instance_id
            or get_recovery_instance_identity().instance_id
        )
        self._buckets: dict[str, _MemoryBucket] = {}
        self._global_lock = threading.Lock()

    @staticmethod
    def scope_key(
        *,
        user_broker_account_id: int | None,
        endpoint_group: str,
        is_public: bool = False,
    ) -> str:
        if is_public or user_broker_account_id is None:
            return f"{SCOPE_PUBLIC}:0:{endpoint_group}"
        return f"{SCOPE_UBA}:{int(user_broker_account_id)}:{endpoint_group}"

    def _bucket(self, key: str) -> _MemoryBucket:
        with self._global_lock:
            if key not in self._buckets:
                self._buckets[key] = _MemoryBucket()
            return self._buckets[key]

    def check_allowed(
        self,
        *,
        user_broker_account_id: int | None,
        endpoint_group: str,
        is_public: bool = False,
    ) -> tuple[bool, str | None, float]:
        """허용 여부, 사유, 대기 초."""

        if not self._enabled:
            return True, None, 0.0
        key = self.scope_key(
            user_broker_account_id=user_broker_account_id,
            endpoint_group=endpoint_group,
            is_public=is_public,
        )
        now = time.monotonic()
        bucket = self._bucket(key)
        with bucket.lock:
            if bucket.blocked_until > now:
                return (
                    False,
                    UpbitRateLimitStatus.BLOCKED_418.value,
                    max(0.0, bucket.blocked_until - now),
                )
            if bucket.cooldown_until > now:
                return (
                    False,
                    UpbitRateLimitStatus.COOLDOWN.value,
                    max(0.0, bucket.cooldown_until - now),
                )
        # PG persistent cooldown (다중 인스턴스)
        pg = self._load_pg_block(
            user_broker_account_id=user_broker_account_id,
            endpoint_group=endpoint_group,
            is_public=is_public,
        )
        if pg is not None:
            status, wait = pg
            if wait > 0:
                # memory에도 반영
                with bucket.lock:
                    if status == UpbitRateLimitStatus.BLOCKED_418.value:
                        bucket.blocked_until = now + wait
                    else:
                        bucket.cooldown_until = now + wait
                return False, status, wait
        return True, None, 0.0

    def wait_if_needed(
        self,
        *,
        user_broker_account_id: int | None,
        endpoint_group: str,
        is_public: bool = False,
        max_wait_seconds: float = 5.0,
    ) -> None:
        allowed, reason, wait = self.check_allowed(
            user_broker_account_id=user_broker_account_id,
            endpoint_group=endpoint_group,
            is_public=is_public,
        )
        if allowed:
            return
        if reason == UpbitRateLimitStatus.BLOCKED_418.value:
            raise UpbitBanOrBlockError(
                "Upbit account API blocked (418 cooldown)",
                http_status=418,
                endpoint_group=endpoint_group,
                retry_after_seconds=wait,
            )
        # 짧은 대기만 인라인 — 긴 대기는 DEFER
        if wait <= max_wait_seconds:
            time.sleep(wait)
            return
        raise UpbitRateLimitError(
            f"Upbit cooldown active for {wait:.1f}s",
            http_status=429,
            endpoint_group=endpoint_group,
            retry_after_seconds=wait,
        )

    def report_response(
        self,
        *,
        user_broker_account_id: int | None,
        endpoint_group: str,
        http_status: int | None,
        snapshot: UpbitRateLimitSnapshot | None,
        is_public: bool = False,
        error_code: str | None = None,
    ) -> None:
        if not self._enabled:
            return
        key = self.scope_key(
            user_broker_account_id=user_broker_account_id,
            endpoint_group=endpoint_group,
            is_public=is_public,
        )
        now_m = time.monotonic()
        bucket = self._bucket(key)
        persist = False
        cooldown = 0.0
        blocked = 0.0
        status = UpbitRateLimitStatus.OK.value

        with bucket.lock:
            if snapshot is not None:
                bucket.remaining_second = snapshot.remaining_second
                bucket.remaining_minute = snapshot.remaining_minute
            if http_status is not None:
                bucket.last_http_status = http_status
            if http_status == 418:
                blocked = max(
                    self._block_418,
                    float(snapshot.retry_after_seconds or 0)
                    if snapshot
                    else self._block_418,
                )
                bucket.blocked_until = now_m + blocked
                bucket.consecutive += 1
                status = UpbitRateLimitStatus.BLOCKED_418.value
                persist = True
            elif http_status == 429:
                cooldown = float(
                    (snapshot.retry_after_seconds if snapshot else None)
                    or 5.0
                )
                bucket.cooldown_until = now_m + cooldown
                bucket.consecutive += 1
                status = UpbitRateLimitStatus.COOLDOWN.value
                persist = cooldown >= self._persist_seconds
            elif http_status and 200 <= http_status < 300:
                bucket.consecutive = 0

        if persist:
            self._persist_pg(
                user_broker_account_id=user_broker_account_id,
                endpoint_group=endpoint_group,
                is_public=is_public,
                status=status,
                cooldown_seconds=cooldown,
                blocked_seconds=blocked,
                http_status=http_status,
                error_code=error_code,
                snapshot=snapshot,
                consecutive=bucket.consecutive,
            )

    def list_states(self, *, limit: int = 100) -> list[dict[str, Any]]:
        from stock_platform.database.session import get_session_factory

        session = get_session_factory()()
        try:
            rows = session.execute(
                select(UpbitApiRateLimitStateEntity)
                .order_by(UpbitApiRateLimitStateEntity.updated_at.desc())
                .limit(limit)
            ).scalars().all()
            return [self._row_dict(r) for r in rows]
        finally:
            session.close()

    def get_uba_states(self, uba_id: int) -> list[dict[str, Any]]:
        from stock_platform.database.session import get_session_factory

        session = get_session_factory()()
        try:
            rows = session.execute(
                select(UpbitApiRateLimitStateEntity).where(
                    UpbitApiRateLimitStateEntity.user_broker_account_id
                    == int(uba_id)
                )
            ).scalars().all()
            return [self._row_dict(r) for r in rows]
        finally:
            session.close()

    def health_summary(self) -> dict[str, Any]:
        from stock_platform.database.session import get_session_factory

        session = get_session_factory()()
        try:
            rows = list(
                session.execute(
                    select(UpbitApiRateLimitStateEntity)
                ).scalars()
            )
            now = datetime.now(timezone.utc)
            cooldown = 0
            blocked = 0
            longest: datetime | None = None
            last_rl: datetime | None = None
            for r in rows:
                if (
                    r.blocked_until
                    and r.blocked_until > now
                ):
                    blocked += 1
                    longest = max(longest, r.blocked_until) if longest else r.blocked_until
                elif (
                    r.cooldown_until
                    and r.cooldown_until > now
                ):
                    cooldown += 1
                    longest = (
                        max(longest, r.cooldown_until)
                        if longest
                        else r.cooldown_until
                    )
                if r.last_http_status in {418, 429} and r.last_response_at:
                    last_rl = (
                        max(last_rl, r.last_response_at)
                        if last_rl
                        else r.last_response_at
                    )
            return {
                "cooldown_account_groups": cooldown,
                "blocked_418_account_groups": blocked,
                "longest_until": longest.isoformat() if longest else None,
                "last_rate_limit_at": (
                    last_rl.isoformat() if last_rl else None
                ),
            }
        finally:
            session.close()

    def _load_pg_block(
        self,
        *,
        user_broker_account_id: int | None,
        endpoint_group: str,
        is_public: bool,
    ) -> tuple[str, float] | None:
        try:
            from stock_platform.database.session import get_session_factory

            session = get_session_factory()()
            try:
                scope = SCOPE_PUBLIC if is_public else SCOPE_UBA
                uba = 0 if is_public else (
                    int(user_broker_account_id)
                    if user_broker_account_id is not None
                    else 0
                )
                row = session.execute(
                    select(UpbitApiRateLimitStateEntity).where(
                        UpbitApiRateLimitStateEntity.credential_scope_type
                        == scope,
                        UpbitApiRateLimitStateEntity.user_broker_account_id
                        == uba,
                        UpbitApiRateLimitStateEntity.endpoint_group
                        == endpoint_group,
                    )
                ).scalar_one_or_none()
                if row is None:
                    return None
                now = datetime.now(timezone.utc)
                if row.blocked_until and row.blocked_until > now:
                    return (
                        UpbitRateLimitStatus.BLOCKED_418.value,
                        (row.blocked_until - now).total_seconds(),
                    )
                if row.cooldown_until and row.cooldown_until > now:
                    return (
                        UpbitRateLimitStatus.COOLDOWN.value,
                        (row.cooldown_until - now).total_seconds(),
                    )
                return None
            finally:
                session.close()
        except Exception:  # noqa: BLE001
            return None

    def _persist_pg(
        self,
        *,
        user_broker_account_id: int | None,
        endpoint_group: str,
        is_public: bool,
        status: str,
        cooldown_seconds: float,
        blocked_seconds: float,
        http_status: int | None,
        error_code: str | None,
        snapshot: UpbitRateLimitSnapshot | None,
        consecutive: int,
    ) -> None:
        try:
            from stock_platform.database.session import get_session_factory

            now = datetime.now(timezone.utc)
            scope = SCOPE_PUBLIC if is_public else SCOPE_UBA
            uba = 0 if is_public else (
                int(user_broker_account_id)
                if user_broker_account_id is not None
                else 0
            )
            cooldown_until = (
                now + timedelta(seconds=cooldown_seconds)
                if cooldown_seconds > 0
                else None
            )
            blocked_until = (
                now + timedelta(seconds=blocked_seconds)
                if blocked_seconds > 0
                else None
            )
            values = {
                "credential_scope_type": scope,
                "user_broker_account_id": uba,
                "endpoint_group": endpoint_group,
                "status": status,
                "remaining_second": (
                    snapshot.remaining_second if snapshot else None
                ),
                "remaining_minute": (
                    snapshot.remaining_minute if snapshot else None
                ),
                "cooldown_until": cooldown_until,
                "blocked_until": blocked_until,
                "last_http_status": http_status,
                "last_error_code": (error_code or "")[:80] or None,
                "last_retry_after_seconds": (
                    int(snapshot.retry_after_seconds)
                    if snapshot and snapshot.retry_after_seconds is not None
                    else None
                ),
                "consecutive_rate_limit_count": consecutive,
                "last_response_at": now,
                "updated_by_instance_id": self._instance_id[:200],
                "updated_at": now,
            }
            session = get_session_factory()()
            try:
                stmt = insert(UpbitApiRateLimitStateEntity).values(
                    **values,
                    created_at=now,
                )
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_upbit_rate_limit_scope_group",
                    set_={
                        k: values[k]
                        for k in values
                        if k
                        not in {
                            "credential_scope_type",
                            "user_broker_account_id",
                            "endpoint_group",
                        }
                    },
                )
                session.execute(stmt)
                session.commit()
            except Exception:  # noqa: BLE001
                session.rollback()
                logger.warning(
                    "upbit_rate_limit_persist_failed",
                    endpoint_group=endpoint_group,
                )
            finally:
                session.close()
        except Exception:  # noqa: BLE001
            logger.warning("upbit_rate_limit_persist_unavailable")

    @staticmethod
    def _row_dict(row: UpbitApiRateLimitStateEntity) -> dict[str, Any]:
        return {
            "id": int(row.upbit_api_rate_limit_state_id),
            "credential_scope_type": row.credential_scope_type,
            "user_broker_account_id": row.user_broker_account_id,
            "endpoint_group": row.endpoint_group,
            "status": row.status,
            "remaining_second": row.remaining_second,
            "remaining_minute": row.remaining_minute,
            "cooldown_until": (
                row.cooldown_until.isoformat()
                if row.cooldown_until
                else None
            ),
            "blocked_until": (
                row.blocked_until.isoformat()
                if row.blocked_until
                else None
            ),
            "last_http_status": row.last_http_status,
            "last_error_code": row.last_error_code,
            "last_retry_after_seconds": row.last_retry_after_seconds,
            "consecutive_rate_limit_count": row.consecutive_rate_limit_count,
            "last_request_at": (
                row.last_request_at.isoformat()
                if row.last_request_at
                else None
            ),
            "last_response_at": (
                row.last_response_at.isoformat()
                if row.last_response_at
                else None
            ),
        }


_COORDINATOR: UpbitRateLimitCoordinator | None = None
_COORDINATOR_LOCK = threading.Lock()


def get_upbit_rate_limit_coordinator() -> UpbitRateLimitCoordinator:
    global _COORDINATOR
    with _COORDINATOR_LOCK:
        if _COORDINATOR is None:
            from stock_platform.common.settings import get_settings

            s = get_settings()
            _COORDINATOR = UpbitRateLimitCoordinator(
                enabled=bool(
                    getattr(s, "upbit_rate_limit_coordinator_enabled", True)
                ),
                persist_cooldown_seconds=float(
                    getattr(
                        s,
                        "upbit_rate_limit_cooldown_persist_seconds",
                        10.0,
                    )
                ),
                default_418_block_seconds=float(
                    getattr(s, "upbit_418_default_block_seconds", 600.0)
                ),
            )
            if (
                not _COORDINATOR._enabled
                and getattr(s, "is_production_env", False)
            ):
                logger.warning(
                    "UPBIT_RATE_LIMIT_COORDINATOR_ENABLED=false "
                    "in production"
                )
        return _COORDINATOR


def reset_upbit_rate_limit_coordinator_for_tests() -> None:
    global _COORDINATOR
    with _COORDINATOR_LOCK:
        _COORDINATOR = None
