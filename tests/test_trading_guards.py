"""Trading Admin 가드 단위 테스트."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.trading_guards import (
    TradingGuardError,
    require_kill_switch_allows_order,
    require_order_safety,
    resolve_broker_adapter_for_cancel,
)
from stock_platform.broker.paper.adapter import PaperBrokerAdapter


def test_kill_switch_blocks_buy_when_active() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.order.trading_guards.PersistentKillSwitchGuard"
    ) as guard_cls:
        guard_cls.return_value.require_order_allowed.side_effect = (
            PermissionError("Global kill switch is active")
        )
        with pytest.raises(TradingGuardError):
            require_kill_switch_allows_order(
                session,
                side="BUY",
            )


def test_require_order_safety_runs_kill_then_risk() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.order.trading_guards.PersistentKillSwitchGuard"
    ) as kill_cls, patch(
        "stock_platform.order.trading_guards.DatabaseBackedRiskOrderGuard"
    ) as risk_cls:
        kill_cls.return_value.require_order_allowed.return_value = None
        risk_cls.return_value.check.return_value = MagicMock(
            allowed=True,
            blocked_reason=None,
        )
        require_order_safety(
            session,
            side="BUY",
            account_number="ACC-1",
            account_id=1,
            exchange_code="KRX",
            symbol="005930",
            quantity=Decimal("1"),
            price=Decimal("70000"),
        )
        kill_cls.return_value.require_order_allowed.assert_called_once()
        risk_cls.return_value.check.assert_called_once()


def test_resolve_broker_adapter_defaults_to_paper() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.order.trading_guards.get_settings"
    ) as settings_fn:
        settings_fn.return_value.kiwoom_live_order_enabled = False
        adapter = resolve_broker_adapter_for_cancel(session)
        assert isinstance(adapter, PaperBrokerAdapter)
