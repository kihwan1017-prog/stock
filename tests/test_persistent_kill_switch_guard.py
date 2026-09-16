from stock_platform.risk_engine.kill_switch_guard import (
    KillSwitchUnavailableError,
    PersistentKillSwitchGuard,
)


class FakeService:
    def __init__(
        self,
        active: bool,
        *,
        exchange_scope: set[str] | None = None,
        raise_on_active: bool = False,
        raise_on_scope: bool = False,
    ):
        self.active = active
        self.exchange_scope = exchange_scope or set()
        self.raise_on_active = raise_on_active
        self.raise_on_scope = raise_on_scope

    def is_active(self):
        if self.raise_on_active:
            raise RuntimeError("db down")
        return self.active

    def is_active_for_scopes(self, scope_codes):
        # GLOBAL 활성 시 전 스코프 활성으로 간주 (단위 테스트 Fake)
        if self.raise_on_active:
            raise RuntimeError("db down")
        return self.active

    def active_exchange_scope(self):
        if self.raise_on_scope:
            raise RuntimeError("db down")
        return set(self.exchange_scope)


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


def test_exchange_scope_blocks_only_matched() -> None:
    guard = PersistentKillSwitchGuard.__new__(
        PersistentKillSwitchGuard
    )
    guard._service = FakeService(
        True,
        exchange_scope={"UPBIT"},
    )

    # KRX는 스코프 밖 → 허용
    guard.require_order_allowed(
        side="BUY",
        exchange_code="KRX",
    )

    try:
        guard.require_order_allowed(
            side="BUY",
            exchange_code="UPBIT",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("UPBIT BUY should be blocked")


def test_fail_closed_when_is_active_raises() -> None:
    guard = PersistentKillSwitchGuard.__new__(
        PersistentKillSwitchGuard
    )
    guard._service = FakeService(
        False,
        raise_on_active=True,
    )

    try:
        guard.require_order_allowed(side="BUY")
    except KillSwitchUnavailableError:
        pass
    else:
        raise AssertionError(
            "KillSwitchUnavailableError expected"
        )

    # SELL은 예외 시에도 허용
    guard.require_order_allowed(
        side="SELL",
        allow_sell=True,
    )
