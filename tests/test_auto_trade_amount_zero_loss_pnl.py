"""Loss round-trip must stamp negative realized_pnl (not only profits)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.operation.autotrading_performance_service import (
    binding_closed_trade_metrics,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_CLOSED,
    OWNERSHIP_STRATEGY,
    StrategyPositionBindingEntity,
)
from stock_platform.risk_engine.strategy_owned_risk_service import (
    StrategyOwnedRiskService,
)


def test_sell_close_stamps_negative_realized_pnl() -> None:
    open_row = SimpleNamespace(
        binding_id=1,
        owned_quantity=Decimal("39.06250000"),
        entry_price=Decimal("256"),
        fees=Decimal("5.00"),
        realized_pnl=Decimal("0"),
        status="OPEN",
        closed_at=None,
        meta_json={},
        entry_order_id=2992,
    )
    session = MagicMock()
    session.scalars.return_value = [open_row]
    session.get.return_value = None  # fee order lookup optional

    svc = StrategyOwnedRiskService(session)
    closed = svc.ensure_binding_from_fill(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=17483,
        deployment_id=None,
        symbol="KRW-ARB",
        entry_order_id=None,
        broker_order_id="sell-uuid",
        quantity=Decimal("39.06250000"),
        entry_price=None,
        side="SELL",
        fees=Decimal("4.98"),
        fill_price=Decimal("255"),
        exit_order_id=2993,
        filled_at=datetime(2026, 9, 6, 0, 25, tzinfo=timezone.utc),
    )

    assert closed is open_row
    assert open_row.status == "CLOSED"
    expected = (Decimal("255") - Decimal("256")) * Decimal("39.06250000")
    assert open_row.realized_pnl == expected
    assert open_row.meta_json.get("closed_quantity") == "39.06250000"


def test_arb_zero_realized_recovers_amounts_from_orders() -> None:
    """구버전 손실 미stamp binding도 order filled_amount로 매수/매도금액 복원."""

    binding = StrategyPositionBindingEntity(
        binding_id=587,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=17483,
        deployment_id=868,
        symbol="KRW-ARB",
        status=BINDING_STATUS_CLOSED,
        ownership_code=OWNERSHIP_STRATEGY,
        entry_order_id=2992,
        owned_quantity=Decimal("0"),
        entry_price=Decimal("256"),
        realized_pnl=Decimal("0"),  # bug residue
        fees=Decimal("9.98"),
        opened_at=datetime(2026, 9, 6, 0, 22, tzinfo=timezone.utc),
        closed_at=datetime(2026, 9, 6, 0, 25, tzinfo=timezone.utc),
        meta_json={"exit_order_id": 2993, "exit_fill_price": "255"},
    )
    entry = TradingOrderEntity(
        order_id=2992,
        client_order_id="buy",
        symbol="KRW-ARB",
        side_code="BUY",
        status_code="FILLED",
        filled_quantity=Decimal("39.06250000"),
        filled_amount=Decimal("10000.00000000"),
        average_fill_price=Decimal("256"),
    )
    exit_o = TradingOrderEntity(
        order_id=2993,
        client_order_id="sell",
        symbol="KRW-ARB",
        side_code="SELL",
        status_code="FILLED",
        filled_quantity=Decimal("39.06250000"),
        filled_amount=Decimal("9960.93750000"),
        average_fill_price=Decimal("255"),
        metadata_payload={"signal_reason": "STOP_LOSS"},
    )
    m = binding_closed_trade_metrics(
        binding, exit_order=exit_o, entry_order=entry
    )
    assert Decimal(str(m["buy_amount"])) == Decimal("10000.00")
    assert Decimal(str(m["sell_amount"])) == Decimal("9960.94")
    assert Decimal(str(m["gross_pnl"])) == Decimal("-39.06")
    assert Decimal(str(m["quantity"])) == Decimal("39.06250000")
    assert Decimal(str(m["entry_cost"])) == Decimal("10000.00")
    net = Decimal(str(m["net_pnl"]))
    assert net == Decimal("-49.04")
