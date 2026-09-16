"""STEP 8-5-18 — Account Identity Hardening tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.risk_engine.daily_loss_models import DailyLossMonitorStatus
from stock_platform.risk_engine.daily_loss_monitor import DailyLossMonitor
from stock_platform.risk_engine.models import RiskDecisionLevel
from stock_platform.risk_engine.order_guard import DatabaseBackedRiskOrderGuard
from stock_platform.trading.account_identity import (
    AccountIdentityError,
    AccountIdentityErrorCode,
    require_live_account_context,
    require_paper_account_context,
    validate_scheduler_account_payload,
)


def test_live_requires_uba() -> None:
    with pytest.raises(AccountIdentityError) as exc:
        require_live_account_context(
            user_id=1,
            user_broker_account_id=None,
            broker_code="KIWOOM",
            account_number="123456",
        )
    assert exc.value.code == AccountIdentityErrorCode.LEGACY_ACCOUNT_NUMBER_ONLY


def test_paper_requires_paper_account_id() -> None:
    with pytest.raises(AccountIdentityError) as exc:
        require_paper_account_context(
            user_id=1,
            paper_account_id=None,
            account_number="P1",
        )
    assert exc.value.code == AccountIdentityErrorCode.LEGACY_ACCOUNT_NUMBER_ONLY


def test_system_shared_blocks_member_snapshot_job() -> None:
    with pytest.raises(AccountIdentityError) as exc:
        validate_scheduler_account_payload(
            {
                "requested_by": "SYSTEM_SHARED",
                "correlation_id": "c1",
            },
            job_type="BROKER_SNAPSHOT",
        )
    assert (
        exc.value.code
        == AccountIdentityErrorCode.SYSTEM_SHARED_ACCOUNT_BLOCKED
    )


def test_system_shared_allows_market_news_job() -> None:
    validate_scheduler_account_payload(
        {"requested_by": "SYSTEM_SHARED"},
        job_type="NEWS",
    )


def test_scheduler_account_number_only_fails() -> None:
    with pytest.raises(AccountIdentityError) as exc:
        validate_scheduler_account_payload(
            {
                "account_number": "123",
                "broker_code": "KIWOOM",
                "requested_by": "admin",
                "correlation_id": "c1",
                "job_type": "SETTLEMENT",
            },
            job_type="SETTLEMENT",
        )
    assert (
        exc.value.code
        == AccountIdentityErrorCode.LEGACY_ACCOUNT_NUMBER_ONLY
    )


def test_scheduler_uba_payload_ok() -> None:
    validate_scheduler_account_payload(
        {
            "user_broker_account_id": 10,
            "broker_code": "KIWOOM",
            "requested_by": "admin",
            "correlation_id": "c1",
            "job_type": "SETTLEMENT",
        },
        job_type="SETTLEMENT",
    )


def test_daily_loss_rejects_account_number_only() -> None:
    monitor = DailyLossMonitor(
        session=MagicMock(),
        loss_limit=Decimal("100000"),
    )
    with pytest.raises(AccountIdentityError):
        asyncio.run(
            monitor.check(broker_code="KIWOOM", account_number="123")
        )


def test_daily_loss_check_uba_safe(monkeypatch) -> None:
    monkeypatch.setattr(
        "stock_platform.risk_engine.daily_loss_repository.AccountDailyLossRepository.upsert_from_snapshot",
        lambda self, snap, **kw: snap,
    )
    account = SimpleNamespace(
        deposit_amount=Decimal("1000000"),
        total_evaluation_amount=Decimal("0"),
        total_profit_loss=Decimal("-10000"),  # 무시 (누적 PnL)
        broker_code="KIWOOM",
        account_number="8130541911",
    )
    session = MagicMock()
    session.get.return_value = SimpleNamespace(broker_code="KIWOOM", user_id=1)
    session.scalar.return_value = 1
    monitor = DailyLossMonitor(
        session=session,
        loss_limit=Decimal("300000"),
    )
    monitor._snapshots = SimpleNamespace(
        get_active_by_uba=lambda _id: (account, [])
    )
    monitor._kill_switch = SimpleNamespace(
        is_active_for_scopes=lambda _scopes: False,
        activate_scope=lambda **_kw: None,
    )
    monitor._events = SimpleNamespace(create=lambda **_kw: None)

    baseline = SimpleNamespace(
        opening_equity=Decimal("1000000"),
        baseline_at=None,
        source_code="TEST",
    )

    class _LossSvc:
        def __init__(self, _session) -> None:
            pass

        def ensure_baseline(self, **kwargs):
            return baseline

        def diagnose(self, **kwargs):
            from datetime import date

            from stock_platform.risk_engine.uba_daily_loss_service import (
                UbaDailyLossBreakdown,
            )

            return UbaDailyLossBreakdown(
                user_broker_account_id=42,
                trading_date=date.today(),
                broker_code="KIWOOM",
                execution_count=0,
                buy_fill_count=0,
                sell_fill_count=0,
                position_count=0,
                snapshot_count=1,
                opening_equity=Decimal("1000000"),
                closing_equity=Decimal("1000000"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                fees=Decimal("0"),
                current_daily_pnl=Decimal("0"),
                current_daily_loss=Decimal("0"),
                max_daily_loss_limit=Decimal("300000"),
                remaining_daily_loss_capacity=Decimal("300000"),
                baseline_at=None,
                baseline_source="TEST",
                correlation_id="test-42",
            )

    monkeypatch.setattr(
        "stock_platform.risk_engine.uba_daily_loss_service.UbaDailyLossService",
        _LossSvc,
    )

    result = asyncio.run(monitor.check_uba(user_broker_account_id=42))
    assert result.user_broker_account_id == 42
    assert result.status == DailyLossMonitorStatus.SAFE
    assert "8130541911" not in result.masked_account_ref


def test_order_guard_live_rejects_missing_uba() -> None:
    session = MagicMock()
    guard = DatabaseBackedRiskOrderGuard(session, broker_code="KIWOOM")
    guard._resolver = SimpleNamespace(
        resolve=lambda **_kw: SimpleNamespace(
            to_engine_policy=lambda: None
        )
    )
    result = guard.check(
        account_number="1234567890",
        account_id=1,
        exchange_code="KRX",
        symbol="005930",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("1000"),
        user_id=1,
        user_broker_account_id=None,
        environment="LIVE",
    )
    assert result.allowed is False
    assert result.blocked_reason == "LEGACY_ACCOUNT_NUMBER_ONLY"
    assert result.evaluation.decision == RiskDecisionLevel.BLOCK


def test_order_guard_paper_rejects_missing_paper_id() -> None:
    session = MagicMock()
    guard = DatabaseBackedRiskOrderGuard(session, broker_code="KIWOOM")
    result = guard.check(
        account_number="",
        account_id=0,
        exchange_code="KRX",
        symbol="005930",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("1000"),
        user_id=1,
        environment="PAPER",
    )
    assert result.allowed is False
    assert result.blocked_reason == "PAPER_ACCOUNT_REQUIRED"


def test_orphan_statuses_include_retired() -> None:
    from stock_platform.broker.snapshot_constants import (
        BrokerSnapshotStatus,
        NON_OPERATIONAL_SNAPSHOT_STATUSES,
    )

    assert BrokerSnapshotStatus.RETIRED.value in NON_OPERATIONAL_SNAPSHOT_STATUSES
    assert BrokerSnapshotStatus.ORPHAN.value in NON_OPERATIONAL_SNAPSHOT_STATUSES


def test_uba_kill_switch_scope_format() -> None:
    from stock_platform.trading.account_identity import (
        paper_kill_switch_scope,
        uba_kill_switch_scope,
    )

    assert uba_kill_switch_scope(12) == "UBA:12"
    assert paper_kill_switch_scope(7) == "PAPER:7"


def test_live_context_ok() -> None:
    ctx = require_live_account_context(
        user_id=1,
        user_broker_account_id=99,
        broker_code="upbit",
        market="CRYPTO",
        currency="KRW",
    )
    assert ctx.user_broker_account_id == 99
    assert ctx.broker_code == "UPBIT"


def test_step8_5_18_revision_head() -> None:
    from tests.migration_helpers import (
        alembic_current_head,
        assert_revision_exists,
    )

    assert_revision_exists("e8f9a0b1c2d3")
    assert_revision_exists("f9a0b1c2d3e4")
    head = alembic_current_head()
    assert_revision_exists(head)
