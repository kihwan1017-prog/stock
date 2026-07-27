import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.risk_engine.daily_loss_models import (
    DailyLossMonitorStatus,
)
from stock_platform.risk_engine.daily_loss_monitor import (
    DailyLossMonitor,
)
from stock_platform.trading.account_identity import AccountIdentityError


class FakeKillSwitch:
    def __init__(self, active=False):
        self.active = active
        self.activated = False
        self.last_scope = None

    def is_active_for_scopes(self, scopes):
        return self.active

    def activate_scope(self, **kwargs):
        self.active = True
        self.activated = True
        self.last_scope = kwargs.get("scope_code")


class FakeEvents:
    def __init__(self):
        self.created = False

    def create(self, **kwargs):
        self.created = True
        return SimpleNamespace(risk_event_id=1)


class FakeNotifier:
    def __init__(self):
        self.sent = False

    async def send(self, **kwargs):
        self.sent = True


def _monitor(*, closing_equity: Decimal, opening_equity: Decimal):
    """Baseline opening vs closing equity 로 일일 손실 시뮬레이션."""

    account = SimpleNamespace(
        deposit_amount=closing_equity,
        total_evaluation_amount=Decimal("0"),
        broker_code="KIWOOM",
        account_number="1234567890",
    )
    session = MagicMock()
    notifier = FakeNotifier()
    monitor = DailyLossMonitor(
        session=session,
        loss_limit=Decimal("300000"),
        notifier=notifier,
    )
    monitor._snapshots = SimpleNamespace(
        get_active_by_uba=lambda _id: (account, [])
    )
    monitor._kill_switch = FakeKillSwitch(False)
    monitor._events = FakeEvents()

    baseline = SimpleNamespace(
        opening_equity=opening_equity,
        baseline_at=None,
        source_code="TEST",
    )

    class _LossSvc:
        def ensure_baseline(self, **kwargs):
            return baseline

        def diagnose(self, **kwargs):
            from stock_platform.risk_engine.uba_daily_loss_service import (
                UbaDailyLossBreakdown,
                daily_loss_from_pnl,
            )

            pnl = (closing_equity - opening_equity).quantize(Decimal("0.01"))
            loss = daily_loss_from_pnl(pnl)
            return UbaDailyLossBreakdown(
                user_broker_account_id=7,
                trading_date=date.today(),
                broker_code="KIWOOM",
                execution_count=0,
                buy_fill_count=0,
                sell_fill_count=0,
                position_count=0,
                snapshot_count=1,
                opening_equity=opening_equity,
                closing_equity=closing_equity,
                realized_pnl=Decimal("0"),
                unrealized_pnl=pnl,
                fees=Decimal("0"),
                current_daily_pnl=pnl,
                current_daily_loss=loss,
                max_daily_loss_limit=Decimal("300000"),
                remaining_daily_loss_capacity=Decimal("300000") - loss,
                baseline_at=None,
                baseline_source="TEST",
                correlation_id="test",
            )

    return monitor, notifier, _LossSvc()


def test_safe_loss_does_not_activate(monkeypatch) -> None:
    monkeypatch.setattr(
        "stock_platform.risk_engine.daily_loss_repository.AccountDailyLossRepository.upsert_from_snapshot",
        lambda self, snap, **kw: snap,
    )
    monitor, notifier, loss_svc = _monitor(
        closing_equity=Decimal("1000000"),
        opening_equity=Decimal("1100000"),  # -100k → SAFE
    )
    monkeypatch.setattr(
        "stock_platform.risk_engine.uba_daily_loss_service.UbaDailyLossService",
        lambda session: loss_svc,
    )

    result = asyncio.run(
        monitor.check_uba(user_broker_account_id=7)
    )

    assert result.status == DailyLossMonitorStatus.SAFE
    assert result.kill_switch_activated is False
    assert notifier.sent is False
    assert result.user_broker_account_id == 7
    assert result.current_loss_amount == Decimal("100000.00")


def test_limit_activates_kill_switch(monkeypatch) -> None:
    monkeypatch.setattr(
        "stock_platform.risk_engine.daily_loss_repository.AccountDailyLossRepository.upsert_from_snapshot",
        lambda self, snap, **kw: snap,
    )
    monitor, notifier, loss_svc = _monitor(
        closing_equity=Decimal("1000000"),
        opening_equity=Decimal("1300000"),  # -300k → LIMIT
    )
    monkeypatch.setattr(
        "stock_platform.risk_engine.uba_daily_loss_service.UbaDailyLossService",
        lambda session: loss_svc,
    )

    result = asyncio.run(
        monitor.check_uba(user_broker_account_id=7)
    )

    assert result.status == DailyLossMonitorStatus.LIMIT_REACHED
    assert result.kill_switch_activated is True
    assert monitor._kill_switch.activated is True
    assert monitor._kill_switch.last_scope == "UBA:7"
    assert monitor._events.created is True
    assert notifier.sent is True


def test_legacy_account_number_path_rejected() -> None:
    monitor, _, _ = _monitor(
        closing_equity=Decimal("1"),
        opening_equity=Decimal("1"),
    )
    with pytest.raises(AccountIdentityError):
        asyncio.run(
            monitor.check(
                broker_code="KIWOOM",
                account_number="123",
            )
        )


def test_profit_yields_zero_daily_loss() -> None:
    from stock_platform.risk_engine.uba_daily_loss_service import (
        daily_loss_from_pnl,
    )

    assert daily_loss_from_pnl(Decimal("5000")) == Decimal("0")
    assert daily_loss_from_pnl(Decimal("-5000")) == Decimal("5000")
