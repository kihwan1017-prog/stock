"""STEP 8-5-6 — PostgreSQL Atomic Lease Lock + Heartbeat + Fencing.

선택: Atomic Lease Row Update (Advisory Session Lock 미사용).
장시간 Broker API 동안 DB Connection을 점유하지 않는다.
시각 기준은 DB NOW()를 사용한다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.broker.recovery_distributed_lock_entities import (
    BrokerRecoveryLockEntity,
)
from stock_platform.broker.recovery_distributed_lock_scope import (
    RecoveryLockScope,
)
from stock_platform.broker.recovery_instance_id import (
    get_recovery_instance_identity,
)
from stock_platform.database.session import get_session_factory

logger = logging.getLogger(__name__)


class LockAcquireResult(StrEnum):
    ACQUIRED = "ACQUIRED"
    BUSY = "BUSY"
    TIMEOUT = "TIMEOUT"
    STALE_TAKEN_OVER = "STALE_TAKEN_OVER"
    ERROR = "ERROR"


class LockReleaseReason(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    SHUTDOWN = "SHUTDOWN"
    LOST_OWNERSHIP = "LOST_OWNERSHIP"


class LockOwnershipLostError(RuntimeError):
    """Heartbeat/Fencing 실패로 Lock 소유권 상실."""


class DistributedLockBusyError(RuntimeError):
    """다른 Owner가 유효 Lease를 보유 중."""

    def __init__(
        self,
        message: str,
        *,
        scope_key: str,
        owner_masked: str | None = None,
        lease_expires_at: str | None = None,
    ) -> None:
        super().__init__(message)
        self.scope_key = scope_key
        self.owner_masked = owner_masked
        self.lease_expires_at = lease_expires_at


@dataclass(slots=True)
class RecoveryLockHandle:
    lock_scope_key: str
    owner_instance_id: str
    lease_id: str
    fencing_token: int
    acquired_at: datetime
    lease_expires_at: datetime
    acquire_result: LockAcquireResult
    lock_row_id: int | None = None
    ownership_lost: bool = False

    def assert_token(self, expected: int) -> None:
        if int(self.fencing_token) != int(expected):
            raise LockOwnershipLostError(
                f"fencing token mismatch: have={self.fencing_token} "
                f"expected={expected}"
            )


class DistributedRecoveryLockManager:
    """계좌 Scope 단위 분산 Lock (짧은 Transaction)."""

    def __init__(
        self,
        *,
        owner_instance_id: str | None = None,
        lease_seconds: int = 120,
        heartbeat_seconds: int = 30,
        acquire_timeout_seconds: float = 5.0,
        enabled: bool = True,
        namespace: str = "stock-platform-recovery",
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be > 0")
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be > 0")
        if heartbeat_seconds >= lease_seconds:
            raise ValueError(
                "heartbeat_seconds must be < lease_seconds"
            )
        if acquire_timeout_seconds < 0:
            raise ValueError("acquire_timeout_seconds must be >= 0")
        if not (namespace or "").strip():
            raise ValueError("namespace must be non-empty")

        self._enabled = enabled
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._acquire_timeout_seconds = acquire_timeout_seconds
        self._namespace = namespace.strip()
        identity = get_recovery_instance_identity(
            override=owner_instance_id
        )
        self._owner_instance_id = identity.instance_id
        self._heartbeat_tasks: dict[str, asyncio.Task] = {}

    @property
    def owner_instance_id(self) -> str:
        return self._owner_instance_id

    @property
    def enabled(self) -> bool:
        return self._enabled

    def acquire(
        self,
        scope: RecoveryLockScope,
        *,
        session: Session | None = None,
        timeout: float | None = None,
    ) -> tuple[LockAcquireResult, RecoveryLockHandle | None]:
        """원자적 Lock 획득. BUSY면 handle=None."""

        if not self._enabled:
            # 개발 전용 bypass — 가짜 handle
            now = datetime.now(timezone.utc)
            return (
                LockAcquireResult.ACQUIRED,
                RecoveryLockHandle(
                    lock_scope_key=scope.lock_scope_key,
                    owner_instance_id=self._owner_instance_id,
                    lease_id=uuid.uuid4().hex,
                    fencing_token=0,
                    acquired_at=now,
                    lease_expires_at=now
                    + timedelta(seconds=self._lease_seconds),
                    acquire_result=LockAcquireResult.ACQUIRED,
                ),
            )

        import time

        timeout_sec = (
            self._acquire_timeout_seconds
            if timeout is None
            else max(0.0, timeout)
        )
        deadline = time.monotonic() + timeout_sec
        owns_session = session is None

        while True:
            sess = session or get_session_factory()()
            try:
                result, handle, _busy = self._try_acquire_once(sess, scope)
                if owns_session:
                    if result in {
                        LockAcquireResult.ACQUIRED,
                        LockAcquireResult.STALE_TAKEN_OVER,
                    }:
                        sess.commit()
                    else:
                        sess.rollback()
                if result in {
                    LockAcquireResult.ACQUIRED,
                    LockAcquireResult.STALE_TAKEN_OVER,
                }:
                    return result, handle
            except Exception:
                if owns_session:
                    sess.rollback()
                raise
            finally:
                if owns_session:
                    sess.close()

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return LockAcquireResult.TIMEOUT, None
            time.sleep(min(0.2, remaining))

    def _try_acquire_once(
        self,
        session: Session,
        scope: RecoveryLockScope,
    ) -> tuple[
        LockAcquireResult,
        RecoveryLockHandle | None,
        dict[str, Any] | None,
    ]:
        lease_id = uuid.uuid4().hex
        owner = self._owner_instance_id
        key = scope.lock_scope_key
        lease_sec = int(self._lease_seconds)

        # 1) row 없으면 INSERT (동시 INSERT는 Unique로 한쪽만 성공)
        session.execute(
            text(
                """
                INSERT INTO operation.broker_recovery_lock (
                    lock_scope_key,
                    account_kind,
                    account_id,
                    user_broker_account_id,
                    paper_account_id,
                    broker_code,
                    market_type,
                    status,
                    fencing_token
                ) VALUES (
                    :key,
                    :kind,
                    :account_id,
                    :uba_id,
                    :paper_id,
                    :broker,
                    :market,
                    'FREE',
                    0
                )
                ON CONFLICT (lock_scope_key) DO NOTHING
                """
            ),
            {
                "key": key,
                "kind": scope.account_kind.value,
                "account_id": scope.account_id,
                "uba_id": (
                    scope.account_id
                    if scope.account_kind.value == "USER_BROKER"
                    else None
                ),
                "paper_id": (
                    scope.account_id
                    if scope.account_kind.value == "PAPER"
                    else None
                ),
                "broker": scope.broker_code.upper(),
                "market": scope.market_type.upper(),
            },
        )

        # Takeover 판별용: 갱신 전 상태
        before = session.execute(
            select(BrokerRecoveryLockEntity).where(
                BrokerRecoveryLockEntity.lock_scope_key == key
            )
        ).scalar_one()
        was_stale_held = before.status == "HELD"

        # 2) 원자적 CAS: FREE/RELEASED 또는 만료 HELD → 획득 (DB NOW())
        row = session.execute(
            text(
                """
                UPDATE operation.broker_recovery_lock
                SET
                    status = 'HELD',
                    owner_instance_id = :owner,
                    lease_id = :lease_id,
                    fencing_token = fencing_token + 1,
                    acquired_at = NOW(),
                    heartbeat_at = NOW(),
                    lease_expires_at = NOW()
                        + make_interval(secs => :lease_sec),
                    released_at = NULL,
                    release_reason = NULL,
                    updated_at = NOW()
                WHERE lock_scope_key = :key
                  AND (
                    status IN ('FREE', 'RELEASED')
                    OR (
                        status = 'HELD'
                        AND lease_expires_at IS NOT NULL
                        AND lease_expires_at < NOW()
                    )
                  )
                RETURNING
                    broker_recovery_lock_id,
                    fencing_token,
                    acquired_at,
                    lease_expires_at,
                    owner_instance_id,
                    lease_id
                """
            ),
            {
                "owner": owner,
                "lease_id": lease_id,
                "lease_sec": lease_sec,
                "key": key,
            },
        ).mappings().first()

        if row is None:
            held = session.execute(
                select(BrokerRecoveryLockEntity).where(
                    BrokerRecoveryLockEntity.lock_scope_key == key
                )
            ).scalar_one_or_none()
            busy_info = {
                "owner_masked": (
                    (held.owner_instance_id or "")[:20] + "…"
                    if held and held.owner_instance_id
                    else None
                ),
                "lease_expires_at": (
                    held.lease_expires_at.isoformat()
                    if held and held.lease_expires_at
                    else None
                ),
            }
            return LockAcquireResult.BUSY, None, busy_info

        token = int(row["fencing_token"])
        acquire_result = (
            LockAcquireResult.STALE_TAKEN_OVER
            if was_stale_held and token > 0
            else LockAcquireResult.ACQUIRED
        )
        handle = RecoveryLockHandle(
            lock_scope_key=key,
            owner_instance_id=str(row["owner_instance_id"]),
            lease_id=str(row["lease_id"]),
            fencing_token=token,
            acquired_at=row["acquired_at"],
            lease_expires_at=row["lease_expires_at"],
            acquire_result=acquire_result,
            lock_row_id=int(row["broker_recovery_lock_id"]),
        )
        return acquire_result, handle, None

    def heartbeat(
        self,
        handle: RecoveryLockHandle,
        *,
        session: Session | None = None,
    ) -> bool:
        """Owner+Lease+Token 일치 시에만 연장. 실패=False."""

        if not self._enabled:
            return True
        owns = session is None
        sess = session or get_session_factory()()
        try:
            row = sess.execute(
                text(
                    """
                    UPDATE operation.broker_recovery_lock
                    SET
                        heartbeat_at = NOW(),
                        lease_expires_at = NOW()
                            + make_interval(secs => :lease_sec),
                        updated_at = NOW()
                    WHERE lock_scope_key = :key
                      AND status = 'HELD'
                      AND owner_instance_id = :owner
                      AND lease_id = :lease_id
                      AND fencing_token = :token
                    RETURNING lease_expires_at, heartbeat_at
                    """
                ),
                {
                    "lease_sec": int(self._lease_seconds),
                    "key": handle.lock_scope_key,
                    "owner": handle.owner_instance_id,
                    "lease_id": handle.lease_id,
                    "token": int(handle.fencing_token),
                },
            ).mappings().first()
            if owns:
                if row:
                    sess.commit()
                else:
                    sess.rollback()
            if not row:
                return False
            handle.lease_expires_at = row["lease_expires_at"]
            return True
        except Exception:
            if owns:
                sess.rollback()
            raise
        finally:
            if owns:
                sess.close()

    def assert_owns(
        self,
        handle: RecoveryLockHandle,
        *,
        session: Session | None = None,
    ) -> None:
        """상태 저장 전 Fencing 검증."""

        if not self._enabled:
            return
        owns = session is None
        sess = session or get_session_factory()()
        try:
            row = sess.execute(
                text(
                    """
                    SELECT 1
                    FROM operation.broker_recovery_lock
                    WHERE lock_scope_key = :key
                      AND status = 'HELD'
                      AND owner_instance_id = :owner
                      AND lease_id = :lease_id
                      AND fencing_token = :token
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at > NOW()
                    """
                ),
                {
                    "key": handle.lock_scope_key,
                    "owner": handle.owner_instance_id,
                    "lease_id": handle.lease_id,
                    "token": int(handle.fencing_token),
                },
            ).first()
            if not row:
                raise LockOwnershipLostError(
                    f"lock ownership lost for {handle.lock_scope_key}"
                )
        finally:
            if owns:
                sess.close()

    def release(
        self,
        handle: RecoveryLockHandle,
        reason: LockReleaseReason | str,
        *,
        session: Session | None = None,
    ) -> bool:
        """Owner+Lease+Token 일치 시에만 해제. 상실 후 강제 해제 불가."""

        if not self._enabled:
            return True
        owns = session is None
        sess = session or get_session_factory()()
        try:
            row = sess.execute(
                text(
                    """
                    UPDATE operation.broker_recovery_lock
                    SET
                        status = 'RELEASED',
                        released_at = NOW(),
                        release_reason = :reason,
                        updated_at = NOW()
                    WHERE lock_scope_key = :key
                      AND status = 'HELD'
                      AND owner_instance_id = :owner
                      AND lease_id = :lease_id
                      AND fencing_token = :token
                    RETURNING broker_recovery_lock_id
                    """
                ),
                {
                    "reason": str(reason)[:40],
                    "key": handle.lock_scope_key,
                    "owner": handle.owner_instance_id,
                    "lease_id": handle.lease_id,
                    "token": int(handle.fencing_token),
                },
            ).first()
            if owns:
                if row:
                    sess.commit()
                else:
                    sess.rollback()
            return row is not None
        except Exception:
            if owns:
                sess.rollback()
            raise
        finally:
            if owns:
                sess.close()

    def bind_recovery_run(
        self,
        handle: RecoveryLockHandle,
        run_id: int,
        *,
        session: Session | None = None,
    ) -> None:
        if not self._enabled:
            return
        owns = session is None
        sess = session or get_session_factory()()
        try:
            sess.execute(
                text(
                    """
                    UPDATE operation.broker_recovery_lock
                    SET recovery_run_id = :run_id, updated_at = NOW()
                    WHERE lock_scope_key = :key
                      AND owner_instance_id = :owner
                      AND lease_id = :lease_id
                      AND fencing_token = :token
                      AND status = 'HELD'
                    """
                ),
                {
                    "run_id": run_id,
                    "key": handle.lock_scope_key,
                    "owner": handle.owner_instance_id,
                    "lease_id": handle.lease_id,
                    "token": int(handle.fencing_token),
                },
            )
            if owns:
                sess.commit()
        except Exception:
            if owns:
                sess.rollback()
            raise
        finally:
            if owns:
                sess.close()

    async def start_heartbeat(self, handle: RecoveryLockHandle) -> None:
        key = handle.lock_scope_key
        await self.stop_heartbeat(key)

        async def _loop() -> None:
            try:
                while True:
                    await asyncio.sleep(self._heartbeat_seconds)
                    ok = await asyncio.to_thread(self.heartbeat, handle)
                    if not ok:
                        handle.ownership_lost = True
                        logger.warning(
                            "recovery lock heartbeat failed scope=%s",
                            key,
                        )
                        raise LockOwnershipLostError(
                            f"heartbeat failed for {key}"
                        )
            except asyncio.CancelledError:
                raise
            except LockOwnershipLostError:
                raise

        self._heartbeat_tasks[key] = asyncio.create_task(
            _loop(), name=f"recovery-lock-hb:{key[:16]}"
        )

    async def stop_heartbeat(self, scope_key: str) -> None:
        task = self._heartbeat_tasks.pop(scope_key, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, LockOwnershipLostError):
            pass
        except Exception:  # noqa: BLE001
            pass

    def list_locks(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        session = get_session_factory()()
        try:
            q = select(BrokerRecoveryLockEntity).order_by(
                BrokerRecoveryLockEntity.updated_at.desc()
            )
            if status:
                q = q.where(BrokerRecoveryLockEntity.status == status)
            rows = session.execute(q.limit(limit)).scalars().all()
            return [r.as_admin_dict() for r in rows]
        finally:
            session.close()

    def get_lock(self, scope_key: str) -> dict[str, Any] | None:
        session = get_session_factory()()
        try:
            row = session.execute(
                select(BrokerRecoveryLockEntity).where(
                    BrokerRecoveryLockEntity.lock_scope_key == scope_key
                )
            ).scalar_one_or_none()
            return row.as_admin_dict() if row else None
        finally:
            session.close()


def build_distributed_lock_manager_from_settings(
    settings: Any | None = None,
    *,
    owner_override: str | None = None,
) -> DistributedRecoveryLockManager:
    from stock_platform.common.settings import get_settings

    s = settings or get_settings()
    return DistributedRecoveryLockManager(
        owner_instance_id=owner_override,
        lease_seconds=int(
            getattr(s, "recovery_lock_lease_seconds", 120)
        ),
        heartbeat_seconds=int(
            getattr(s, "recovery_lock_heartbeat_seconds", 30)
        ),
        acquire_timeout_seconds=float(
            getattr(s, "recovery_lock_acquire_timeout_seconds", 5.0)
        ),
        enabled=bool(
            getattr(s, "recovery_distributed_lock_enabled", True)
        ),
        namespace=str(
            getattr(
                s,
                "recovery_lock_namespace",
                "stock-platform-recovery",
            )
        ),
    )
