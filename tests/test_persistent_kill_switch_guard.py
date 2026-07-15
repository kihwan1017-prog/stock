from stock_platform.risk_engine.kill_switch_guard import (
    PersistentKillSwitchGuard,
)


class FakeService:
    def __init__(self, active: bool):
        self.active = active

    def is_active(self):
        return self.active


def test_blocks_buy_when_active() -> None:
    guard = PersistentKillSwitchGuard.__new__(
        PersistentKillSwitchGuard
    )
    guard._service = FakeService(True)

    try:
        guard.require_order_allowed(
            side="BUY",
            allow_sell=True,
        )
    except PermissionError:
        pass
    else:
        raise AssertionError(
            "PermissionError was not raised"
        )


def test_allows_sell_when_active() -> None:
    guard = PersistentKillSwitchGuard.__new__(
        PersistentKillSwitchGuard
    )
    guard._service = FakeService(True)

    guard.require_order_allowed(
        side="SELL",
        allow_sell=True,
    )
