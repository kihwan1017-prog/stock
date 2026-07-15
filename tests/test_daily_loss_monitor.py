import asyncio
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.risk_engine.daily_loss_models import (
    DailyLossMonitorStatus,
)
from stock_platform.risk_engine.daily_loss_monitor import (
    DailyLossMonitor,
)


class FakeScalars:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class FakeSession:
    def __init__(self, account, positions):
        self.account = account
        self.positions = positions

    def scalar(self, statement):
        return self.account

    def scalars(self, statement):
        return FakeScalars(self.positions)

    def add(self, entity):
        pass

    def commit(self):
        pass

    def refresh(self, entity):
        if getattr(entity, "risk_event_id", None) is None:
            entity.risk_event_id = 1


class FakeKillSwitch:
    def __init__(self, active=False):
        self.active = active
        self.activated = False

    def is_active(self):
        return self.active

    def activate(self, **kwargs):
        self.active = True
        self.activated = True


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


def _monitor(loss: str):
    account = SimpleNamespace(
        total_profit_loss=Decimal(loss)
    )
    session = FakeSession(account, [])
    notifier = FakeNotifier()

    monitor = DailyLossMonitor(
        session=session,
        loss_limit=Decimal("300000"),
        notifier=notifier,
    )
    monitor._kill_switch = FakeKillSwitch(False)
    monitor._events = FakeEvents()
    return monitor, notifier


def test_safe_loss_does_not_activate() -> None:
    monitor, notifier = _monitor("-100000")

    result = asyncio.run(
        monitor.check(
            broker_code="KIWOOM",
            account_number="123",
        )
    )

    assert result.status == DailyLossMonitorStatus.SAFE
    assert result.kill_switch_activated is False
    assert notifier.sent is False


def test_limit_activates_kill_switch() -> None:
    monitor, notifier = _monitor("-300000")

    result = asyncio.run(
        monitor.check(
            broker_code="KIWOOM",
            account_number="123",
        )
    )

    assert result.status == (
        DailyLossMonitorStatus.LIMIT_REACHED
    )
    assert result.kill_switch_activated is True
    assert monitor._kill_switch.activated is True
    assert monitor._events.created is True
    assert notifier.sent is True
