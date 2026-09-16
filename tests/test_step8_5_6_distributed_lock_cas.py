"""STEP 8-5-6 — Distributed Lock CAS / Heartbeat / Release (mocked SQL)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.recovery_distributed_lock import (
    DistributedRecoveryLockManager,
    LockAcquireResult,
    LockOwnershipLostError,
    LockReleaseReason,
    RecoveryLockHandle,
)
from stock_platform.broker.recovery_distributed_lock_scope import (
    RecoveryAccountKind,
    RecoveryLockScope,
)


def _scope(account_id: int = 7) -> RecoveryLockScope:
    return RecoveryLockScope(
        account_kind=RecoveryAccountKind.USER_BROKER,
        account_id=account_id,
        broker_code="UPBIT",
        market_type="CRYPTO",
    )


def test_acquire_busy_when_update_returns_none() -> None:
    mgr = DistributedRecoveryLockManager(
        enabled=True,
        owner_instance_id="inst-a",
        lease_seconds=120,
        heartbeat_seconds=30,
        acquire_timeout_seconds=0,
    )
    session = MagicMock()
    # INSERT ON CONFLICT
    session.execute.side_effect = [
        MagicMock(),  # insert
        MagicMock(
            scalar_one=MagicMock(
                return_value=MagicMock(status="HELD", lease_expires_at=None)
            )
        ),  # before
        MagicMock(mappings=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))),  # update none
        MagicMock(
            scalar_one_or_none=MagicMock(
                return_value=MagicMock(
                    owner_instance_id="inst-b:pid:uuid",
                    lease_expires_at=datetime.now(timezone.utc),
                )
            )
        ),
    ]
    result, handle, busy = mgr._try_acquire_once(session, _scope())
    assert result == LockAcquireResult.BUSY
    assert handle is None
    assert busy is not None


def test_acquire_success_increments_fencing() -> None:
    mgr = DistributedRecoveryLockManager(
        enabled=True,
        owner_instance_id="inst-a",
        lease_seconds=120,
        heartbeat_seconds=30,
        acquire_timeout_seconds=0,
    )
    now = datetime.now(timezone.utc)
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(),  # insert
        MagicMock(
            scalar_one=MagicMock(
                return_value=MagicMock(status="FREE")
            )
        ),
        MagicMock(
            mappings=MagicMock(
                return_value=MagicMock(
                    first=MagicMock(
                        return_value={
                            "broker_recovery_lock_id": 1,
                            "fencing_token": 1,
                            "acquired_at": now,
                            "lease_expires_at": now,
                            "owner_instance_id": "inst-a",
                            "lease_id": "lease-1",
                        }
                    )
                )
            )
        ),
    ]
    result, handle, busy = mgr._try_acquire_once(session, _scope())
    assert result == LockAcquireResult.ACQUIRED
    assert handle is not None
    assert handle.fencing_token == 1
    assert busy is None


def test_stale_takeover_result() -> None:
    mgr = DistributedRecoveryLockManager(
        enabled=True,
        owner_instance_id="inst-b",
        lease_seconds=120,
        heartbeat_seconds=30,
        acquire_timeout_seconds=0,
    )
    now = datetime.now(timezone.utc)
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(),
        MagicMock(
            scalar_one=MagicMock(
                return_value=MagicMock(status="HELD")
            )
        ),
        MagicMock(
            mappings=MagicMock(
                return_value=MagicMock(
                    first=MagicMock(
                        return_value={
                            "broker_recovery_lock_id": 2,
                            "fencing_token": 11,
                            "acquired_at": now,
                            "lease_expires_at": now,
                            "owner_instance_id": "inst-b",
                            "lease_id": "lease-2",
                        }
                    )
                )
            )
        ),
    ]
    result, handle, _ = mgr._try_acquire_once(session, _scope())
    assert result == LockAcquireResult.STALE_TAKEN_OVER
    assert handle is not None
    assert handle.fencing_token == 11


def test_heartbeat_rejects_wrong_owner() -> None:
    mgr = DistributedRecoveryLockManager(
        enabled=True,
        owner_instance_id="inst-a",
        lease_seconds=120,
        heartbeat_seconds=30,
    )
    handle = RecoveryLockHandle(
        lock_scope_key="rlk:x",
        owner_instance_id="inst-a",
        lease_id="lease-1",
        fencing_token=3,
        acquired_at=datetime.now(timezone.utc),
        lease_expires_at=datetime.now(timezone.utc),
        acquire_result=LockAcquireResult.ACQUIRED,
    )
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = (
        None
    )
    assert mgr.heartbeat(handle, session=session) is False


def test_release_requires_matching_token() -> None:
    mgr = DistributedRecoveryLockManager(
        enabled=True,
        owner_instance_id="inst-a",
        lease_seconds=120,
        heartbeat_seconds=30,
    )
    handle = RecoveryLockHandle(
        lock_scope_key="rlk:x",
        owner_instance_id="inst-a",
        lease_id="lease-1",
        fencing_token=3,
        acquired_at=datetime.now(timezone.utc),
        lease_expires_at=datetime.now(timezone.utc),
        acquire_result=LockAcquireResult.ACQUIRED,
    )
    session = MagicMock()
    session.execute.return_value.first.return_value = None
    assert (
        mgr.release(handle, LockReleaseReason.SUCCESS, session=session)
        is False
    )


def test_assert_owns_raises_when_missing() -> None:
    mgr = DistributedRecoveryLockManager(
        enabled=True,
        owner_instance_id="inst-a",
        lease_seconds=120,
        heartbeat_seconds=30,
    )
    handle = RecoveryLockHandle(
        lock_scope_key="rlk:x",
        owner_instance_id="inst-a",
        lease_id="lease-1",
        fencing_token=3,
        acquired_at=datetime.now(timezone.utc),
        lease_expires_at=datetime.now(timezone.utc),
        acquire_result=LockAcquireResult.ACQUIRED,
    )
    session = MagicMock()
    session.execute.return_value.first.return_value = None
    with pytest.raises(LockOwnershipLostError):
        mgr.assert_owns(handle, session=session)


def test_parallel_accounts_different_scopes() -> None:
    s1 = _scope(1)
    s2 = _scope(2)
    assert s1.lock_scope_key != s2.lock_scope_key


@patch(
    "stock_platform.broker.recovery_distributed_lock.get_session_factory"
)
def test_acquire_timeout_returns_timeout(mock_sf) -> None:
    mgr = DistributedRecoveryLockManager(
        enabled=True,
        owner_instance_id="inst-a",
        lease_seconds=120,
        heartbeat_seconds=30,
        acquire_timeout_seconds=0,
    )
    session = MagicMock()
    mock_sf.return_value = MagicMock(return_value=session)

    def _busy_once(sess, scope):
        return LockAcquireResult.BUSY, None, {"owner_masked": "x"}

    mgr._try_acquire_once = _busy_once  # type: ignore[method-assign]
    result, handle = mgr.acquire(_scope())
    assert result == LockAcquireResult.TIMEOUT
    assert handle is None
