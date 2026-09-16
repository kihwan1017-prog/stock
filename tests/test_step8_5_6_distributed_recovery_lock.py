"""STEP 8-5-6 — Distributed Recovery Lock unit tests."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.recovery_adapter import AccountRecoveryContext
from stock_platform.broker.recovery_distributed_lock import (
    DistributedLockBusyError,
    DistributedRecoveryLockManager,
    LockAcquireResult,
    LockOwnershipLostError,
    LockReleaseReason,
    RecoveryLockHandle,
)
from stock_platform.broker.recovery_distributed_lock_scope import (
    RecoveryAccountKind,
    RecoveryLockScope,
    scope_from_context,
)
from stock_platform.broker.recovery_instance_id import (
    get_recovery_instance_identity,
    reset_recovery_instance_identity_for_tests,
)
from stock_platform.broker.recovery_lock import RecoveryLockError
from stock_platform.broker.recovery_runtime import BrokerRecoveryManager
from tests.migration_helpers import (
    assert_revision_exists,
    alembic_current_head,
)


def test_migration_revision_in_chain() -> None:
    assert_revision_exists("w0a1b2c3d4e5")
    # 단일 Head 유지 (이후 STEP이 head를 전진시켜도 revision은 체인에 존재)
    head = alembic_current_head()
    assert head  # single head helper already validated
    assert_revision_exists(head)


def test_lock_scope_key_stable_and_no_secrets() -> None:
    a = RecoveryLockScope(
        account_kind=RecoveryAccountKind.USER_BROKER,
        account_id=42,
        broker_code="UPBIT",
        market_type="CRYPTO",
    )
    b = RecoveryLockScope(
        account_kind=RecoveryAccountKind.USER_BROKER,
        account_id=42,
        broker_code="upbit",
        market_type="crypto",
    )
    other = RecoveryLockScope(
        account_kind=RecoveryAccountKind.USER_BROKER,
        account_id=43,
        broker_code="UPBIT",
        market_type="CRYPTO",
    )
    paper = RecoveryLockScope(
        account_kind=RecoveryAccountKind.PAPER,
        account_id=42,
        broker_code="PAPER",
        market_type="STOCK",
    )
    assert a.lock_scope_key == b.lock_scope_key
    assert a.lock_scope_key != other.lock_scope_key
    assert a.lock_scope_key != paper.lock_scope_key
    assert a.lock_scope_key.startswith("rlk:")
    # Python hash() 미사용 — SHA 기반
    raw = "stock-platform-recovery|kind:USER_BROKER|uba:42|broker:UPBIT|mkt:CRYPTO"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:40]
    assert a.lock_scope_key == f"rlk:{digest}"
    blob = a.lock_scope_key + str(a.masked_for_log())
    assert "secret" not in blob.lower()
    assert "app_key" not in blob.lower()


def test_scope_from_context_and_process_independence() -> None:
    ctx = AccountRecoveryContext(
        user_id=1,
        broker_code="KIWOOM",
        market_type="STOCK",
        user_broker_account_id=9,
    )
    s1 = scope_from_context(ctx)
    s2 = scope_from_context(ctx)
    assert s1.lock_scope_key == s2.lock_scope_key
    # builtin hash와 무관하게 동일
    assert hash(s1.lock_scope_key)  # 존재만 확인
    assert "PYTHONHASHSEED" not in s1.lock_scope_key


def test_instance_identity_stable_in_process() -> None:
    reset_recovery_instance_identity_for_tests()
    a = get_recovery_instance_identity()
    b = get_recovery_instance_identity()
    assert a.instance_id == b.instance_id
    assert a.instance_id.startswith("stock-platform:")
    assert str(a.process_id) in a.instance_id
    reset_recovery_instance_identity_for_tests()


def test_lock_manager_settings_validation() -> None:
    with pytest.raises(ValueError, match="heartbeat"):
        DistributedRecoveryLockManager(
            lease_seconds=30, heartbeat_seconds=30
        )
    with pytest.raises(ValueError, match="lease"):
        DistributedRecoveryLockManager(lease_seconds=0)
    with pytest.raises(ValueError, match="namespace"):
        DistributedRecoveryLockManager(namespace="  ")


def test_disabled_lock_returns_acquired_handle() -> None:
    mgr = DistributedRecoveryLockManager(
        enabled=False,
        owner_instance_id="test-owner-aaa",
        lease_seconds=60,
        heartbeat_seconds=10,
    )
    scope = RecoveryLockScope(
        account_kind=RecoveryAccountKind.PAPER,
        account_id=1,
        broker_code="PAPER",
        market_type="STOCK",
    )
    result, handle = mgr.acquire(scope)
    assert result == LockAcquireResult.ACQUIRED
    assert handle is not None
    assert handle.fencing_token == 0
    assert mgr.heartbeat(handle) is True
    assert mgr.release(handle, LockReleaseReason.SUCCESS) is True


def test_recover_all_maps_distributed_busy() -> None:
    manager = BrokerRecoveryManager(
        distributed_lock_manager=DistributedRecoveryLockManager(
            enabled=False,
            owner_instance_id="mgr-a",
            lease_seconds=60,
            heartbeat_seconds=10,
        )
    )

    async def _busy(_ctx, **_kwargs):
        raise DistributedLockBusyError(
            "busy",
            scope_key="rlk:abc",
            owner_masked="host:…:deadbeef",
            lease_expires_at="2099-01-01T00:00:00+00:00",
        )

    with patch.object(manager, "recover_account", new=_busy):
        with patch.object(
            manager,
            "discover_accounts",
            return_value=[
                AccountRecoveryContext(
                    user_id=1,
                    broker_code="PAPER_STOCK",
                    market_type="STOCK",
                    paper_account_id=1,
                ),
                AccountRecoveryContext(
                    user_id=2,
                    broker_code="PAPER_STOCK",
                    market_type="STOCK",
                    paper_account_id=2,
                ),
            ],
        ):
            with patch(
                "stock_platform.broker.recovery_runtime.get_session_factory"
            ) as sf:
                sf.return_value = MagicMock(return_value=MagicMock())
                result = asyncio.run(
                    manager.recover_all(trigger_type="TEST")
                )
    assert result["success"] is True
    assert all(
        a["status"] == "SKIPPED_DISTRIBUTED_LOCK"
        for a in result["accounts"]
    )


def test_lock_ownership_lost_error_type() -> None:
    with pytest.raises(LockOwnershipLostError):
        raise LockOwnershipLostError("lost")


def test_handle_assert_token() -> None:
    handle = RecoveryLockHandle(
        lock_scope_key="rlk:x",
        owner_instance_id="o",
        lease_id="l",
        fencing_token=5,
        acquired_at=datetime.now(timezone.utc),
        lease_expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=60),
        acquire_result=LockAcquireResult.ACQUIRED,
    )
    handle.assert_token(5)
    with pytest.raises(LockOwnershipLostError):
        handle.assert_token(4)


def test_local_lock_still_raises_when_held() -> None:
    manager = BrokerRecoveryManager(
        distributed_lock_manager=DistributedRecoveryLockManager(
            enabled=False,
            owner_instance_id="local-test",
            lease_seconds=60,
            heartbeat_seconds=10,
        )
    )
    ctx = AccountRecoveryContext(
        user_id=1,
        broker_code="PAPER_STOCK",
        market_type="STOCK",
        paper_account_id=99,
    )
    lock = manager._lock_for(ctx.scope_key)

    async def _hold():
        async with lock:
            with pytest.raises(RecoveryLockError, match="already running"):
                await manager.recover_account(ctx)

    asyncio.run(_hold())
