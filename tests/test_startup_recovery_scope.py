"""SHARED — Startup recovery scope: no recover_all / broker adapter on startup."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_lock import RecoveryAccountLockService
from stock_platform.broker.recovery_runtime import BrokerRecoveryManager


class _MemSession:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = list(rows or [])
        self.committed = 0
        self.rolled_back = 0
        self.flushed = 0

    def scalars(self, stmt: Any) -> Any:
        # finalize 쿼리는 RUNNING + expired 만 — 테스트용 필터
        now = datetime.now(timezone.utc)
        matched = [
            r
            for r in self.rows
            if getattr(r, "recovery_status", None) == "RUNNING"
            and getattr(r, "lock_expires_at", None) is not None
            and r.lock_expires_at <= now
        ]
        return matched

    def scalar(self, stmt: Any) -> Any:
        return None

    def flush(self) -> None:
        self.flushed += 1

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        return None

    def add(self, obj: Any) -> None:
        self.rows.append(obj)


def _state(
    *,
    status: str = "SUCCESS",
    paused: bool = True,
    expires_in_sec: int | None = None,
    expired: bool = False,
    uba: int = 1381,
    broker: str = "KIWOOM",
) -> BrokerRecoveryAccountStateEntity:
    now = datetime.now(timezone.utc)
    row = BrokerRecoveryAccountStateEntity(
        broker_code=broker,
        user_id=61,
        paper_account_id=None,
        user_broker_account_id=uba,
        recovery_status=status,
        trading_paused=paused,
        lock_holder="test-holder" if status == "RUNNING" else None,
        lock_expires_at=None,
        last_error_summary=None,
        updated_at=now,
    )
    if status == "RUNNING":
        if expired:
            row.lock_expires_at = now - timedelta(seconds=30)
        elif expires_in_sec is not None:
            row.lock_expires_at = now + timedelta(seconds=expires_in_sec)
        else:
            row.lock_expires_at = now + timedelta(seconds=300)
    return row


@pytest.mark.asyncio
async def test_startup_state_only_does_not_call_recover_all_or_adapters():
    manager = BrokerRecoveryManager()
    session = _MemSession(
        [
            _state(status="SUCCESS", paused=True, uba=1381, broker="KIWOOM"),
            _state(status="SUCCESS", paused=False, uba=1380, broker="UPBIT"),
        ]
    )

    with (
        patch(
            "stock_platform.broker.recovery_runtime.get_session_factory",
            return_value=lambda: session,
        ),
        patch.object(
            manager, "recover_all", new_callable=AsyncMock
        ) as mock_all,
        patch.object(
            manager, "recover_account", new_callable=AsyncMock
        ) as mock_acct,
        patch.object(
            manager, "discover_accounts", return_value=["SHOULD_NOT"]
        ) as mock_disc,
    ):
        result = await manager.recover_startup_state_only(actor="STARTUP")

    assert result["recover_all_called"] is False
    assert result["broker_adapter_calls"] == 0
    assert result["account_count"] == 0
    assert result["trigger_type"] == "STARTUP_STATE_ONLY"
    mock_all.assert_not_awaited()
    mock_acct.assert_not_awaited()
    mock_disc.assert_not_called()


@pytest.mark.asyncio
async def test_startup_isolates_healthy_upbit_kiwoom_paper():
    """A/B/G/H/I — healthy accounts → startup broker recovery 0."""

    manager = BrokerRecoveryManager()
    session = _MemSession(
        [
            _state(status="SUCCESS", paused=False, uba=1380, broker="UPBIT"),
            _state(status="SUCCESS", paused=True, uba=1381, broker="KIWOOM"),
            _state(status="SUCCESS", paused=False, uba=0, broker="PAPER_STOCK"),
        ]
    )
    # Paper row uses paper_account_id
    session.rows[2].user_broker_account_id = None
    session.rows[2].paper_account_id = 7

    with (
        patch(
            "stock_platform.broker.recovery_runtime.get_session_factory",
            return_value=lambda: session,
        ),
        patch.object(manager, "recover_all", new_callable=AsyncMock) as mock_all,
        patch.object(
            manager, "recover_account", new_callable=AsyncMock
        ) as mock_acct,
    ):
        result = await manager.recover_startup_state_only()

    assert result["broker_adapter_calls"] == 0
    mock_all.assert_not_awaited()
    mock_acct.assert_not_awaited()
    # pause 유지
    assert session.rows[1].trading_paused is True
    assert session.rows[1].recovery_status == "SUCCESS"
    assert session.rows[0].recovery_status == "SUCCESS"


def test_finalize_expired_orphan_only_local():
    expired = _state(status="RUNNING", paused=True, expired=True, uba=99)
    active = _state(status="RUNNING", paused=True, expires_in_sec=120, uba=100)
    healthy = _state(status="SUCCESS", paused=True, uba=1381)
    session = _MemSession([expired, active, healthy])

    # scalars 필터를 실제 서비스와 맞추기 위해 직접 호출
    summary = RecoveryAccountLockService(session).finalize_expired_orphan_states(
        actor="STARTUP"
    )
    assert summary["finalized"] == 1
    assert expired.recovery_status == "FAILED"
    assert expired.trading_paused is True
    assert expired.lock_holder is None
    assert expired.lock_expires_at is None
    assert "orphan_lock_expired" in (expired.last_error_summary or "")
    # 미만료 RUNNING / SUCCESS 불변
    assert active.recovery_status == "RUNNING"
    assert healthy.recovery_status == "SUCCESS"


@pytest.mark.asyncio
async def test_startup_finalizes_expired_orphan_without_broker():
    expired = _state(status="RUNNING", paused=True, expired=True, uba=55)
    session = _MemSession([expired])
    manager = BrokerRecoveryManager()

    with (
        patch(
            "stock_platform.broker.recovery_runtime.get_session_factory",
            return_value=lambda: session,
        ),
        patch.object(manager, "recover_all", new_callable=AsyncMock) as mock_all,
    ):
        result = await manager.recover_startup_state_only(actor="STARTUP")

    assert result["orphan_finalization"]["finalized"] == 1
    assert expired.recovery_status == "FAILED"
    assert expired.trading_paused is True
    mock_all.assert_not_awaited()
    assert session.committed == 1


@pytest.mark.asyncio
async def test_lifecycle_startup_broker_recovery_uses_state_only():
    from stock_platform.api.lifecycle import ApplicationLifecycle

    life = ApplicationLifecycle()
    mock_mgr = MagicMock()
    mock_mgr.recover_startup_state_only = AsyncMock(
        return_value={"recover_all_called": False, "success": True}
    )
    mock_mgr.recover = AsyncMock()
    mock_mgr._startup_finished_at = None

    with patch(
        "stock_platform.api.lifecycle.broker_recovery_manager",
        mock_mgr,
    ):
        await life._startup_broker_recovery()

    mock_mgr.recover_startup_state_only.assert_awaited_once()
    mock_mgr.recover.assert_not_awaited()
    assert mock_mgr._startup_finished_at is not None


@pytest.mark.asyncio
async def test_manual_recover_all_still_available():
    """G/H/I — manual recover_all 경로 유지 (startup과 분리)."""

    manager = BrokerRecoveryManager()
    with patch.object(
        manager,
        "discover_accounts",
        return_value=[],
    ), patch(
        "stock_platform.broker.recovery_runtime.get_session_factory",
        return_value=lambda: _MemSession(),
    ):
        result = await manager.recover_all(
            trigger_type="MANUAL",
            user_broker_account_id=1381,
            broker_code="KIWOOM",
            requested_by="test",
        )
    assert result["trigger_type"] == "MANUAL"
    assert result["account_count"] == 0


def test_historical_stale_recovery_run_not_in_finalize_scope():
    """L — recovery_run RUNNING은 account_state finalize 대상이 아님."""

    # account_state만 다루는 API — recovery_run 테이블 미참조
    import inspect

    src = inspect.getsource(
        RecoveryAccountLockService.finalize_expired_orphan_states
    )
    assert "BrokerRecoveryRun" not in src
    assert "recovery_run" not in src.lower() or "account" in src.lower()
    assert "BrokerRecoveryAccountStateEntity" in src


@pytest.mark.asyncio
async def test_failed_and_credential_missing_not_broker_called_on_startup():
    manager = BrokerRecoveryManager()
    session = _MemSession(
        [
            _state(status="FAILED", paused=True, uba=1408, broker="UPBIT"),
            _state(status="FAILED", paused=True, uba=1410, broker="KIWOOM"),
        ]
    )
    with (
        patch(
            "stock_platform.broker.recovery_runtime.get_session_factory",
            return_value=lambda: session,
        ),
        patch.object(manager, "recover_all", new_callable=AsyncMock) as mock_all,
        patch.object(
            manager, "recover_account", new_callable=AsyncMock
        ) as mock_acct,
    ):
        await manager.recover_startup_state_only()
    mock_all.assert_not_awaited()
    mock_acct.assert_not_awaited()
    assert session.rows[0].recovery_status == "FAILED"
    assert session.rows[0].trading_paused is True
