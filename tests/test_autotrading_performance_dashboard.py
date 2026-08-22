"""AUTO trading performance dashboard — aggregation + MANUAL exclusion."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from stock_platform.operation.autotrading_performance_service import (
    AutotradingPerformanceService,
    binding_closed_trade_metrics,
    classify_exit_reason,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_CLOSED,
    BINDING_STATUS_OPEN,
    OWNERSHIP_STRATEGY,
    StrategyPositionBindingEntity,
)


def _geod_closed_binding() -> StrategyPositionBindingEntity:
    """GEOD 첫 round-trip 근사 — entry 347, exit 350, net ≈ +38.21."""

    return StrategyPositionBindingEntity(
        binding_id=1,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=100,
        deployment_id=200,
        symbol="KRW-GEOD",
        status=BINDING_STATUS_CLOSED,
        ownership_code=OWNERSHIP_STRATEGY,
        entry_order_id=1800,
        owned_quantity=Decimal("0"),
        entry_price=Decimal("347"),
        realized_pnl=Decimal("40.50"),
        fees=Decimal("2.29"),
        opened_at=datetime(2026, 8, 21, 5, 0, tzinfo=timezone.utc),
        closed_at=datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc),
        meta_json={
            "exit_order_id": 1801,
            "exit_fill_price": "350",
            "closed_quantity": "1.15",
        },
    )


def test_classify_exit_reason_ma_dead_cross() -> None:
    assert classify_exit_reason("MA_DEAD_CROSS") == "STRATEGY_SIGNAL"
    assert classify_exit_reason("STOP_LOSS") == "STOP_LOSS"
    assert classify_exit_reason("TAKE_PROFIT") == "TAKE_PROFIT"
    assert classify_exit_reason("TRAILING_STOP") == "TRAILING_STOP"


def test_geod_closed_trade_metrics() -> None:
    binding = _geod_closed_binding()
    exit_order = TradingOrderEntity(
        order_id=1801,
        client_order_id="c-exit",
        symbol="KRW-GEOD",
        side_code="SELL",
        status_code="FILLED",
        metadata_payload={"signal_reason": "MA_DEAD_CROSS"},
    )
    m = binding_closed_trade_metrics(binding, exit_order=exit_order)
    assert m["entry_order_id"] == 1800
    assert m["exit_order_id"] == 1801
    assert m["exit_reason_category"] == "STRATEGY_SIGNAL"
    net = Decimal(str(m["net_pnl"]))
    assert net == Decimal("38.21")
    cost = Decimal(str(m["entry_cost"]))
    assert cost > Decimal("0")
    ret = Decimal(str(m["return_pct"]))
    assert ret > Decimal("0")


def _mock_session(
    *,
    closed: list | None = None,
    open_bindings: list | None = None,
    exit_orders: list | None = None,
    snapshots: list | None = None,
) -> MagicMock:
    """scalars 호출 순서: CLOSED bindings → OPEN → exit orders → mark prices."""

    session = MagicMock()
    queues = [
        iter(closed or []),
        iter(open_bindings or []),
        iter(exit_orders or []),
        iter(snapshots or []),
    ]

    def _scalars(_stmt):  # noqa: ANN001
        if queues:
            return queues.pop(0)
        return iter([])

    session.scalars = MagicMock(side_effect=_scalars)
    return session


def test_manual_binding_excluded_from_service_query() -> None:
    """ownership_code=MANUAL binding은 DB 쿼리 필터로 제외 — 서비스는 AUTO만 수신."""

    auto = _geod_closed_binding()
    session = _mock_session(closed=[auto])
    out = AutotradingPerformanceService(session).build(period="ALL")
    assert out["closed_trade_count"] == 1
    assert out["recent_closed_trades"][0]["symbol"] == "KRW-GEOD"


def test_empty_state_no_fake_data() -> None:
    session = _mock_session()
    out = AutotradingPerformanceService(session).build(period="30D")
    assert out["closed_trade_count"] == 0
    assert out["summary"]["closed_trade_count"] == 0
    assert out["daily_returns"] == []
    assert out["low_sample_warning"] is True


def test_win_loss_classification() -> None:
    win = _geod_closed_binding()
    loss = StrategyPositionBindingEntity(
        binding_id=2,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=100,
        symbol="KRW-X",
        status=BINDING_STATUS_CLOSED,
        ownership_code=OWNERSHIP_STRATEGY,
        owned_quantity=Decimal("0"),
        entry_price=Decimal("100"),
        realized_pnl=Decimal("-10"),
        fees=Decimal("0"),
        closed_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        meta_json={"exit_fill_price": "90", "closed_quantity": "1"},
    )
    exit_order = TradingOrderEntity(
        order_id=1801,
        client_order_id="c-exit",
        symbol="KRW-GEOD",
        side_code="SELL",
        status_code="FILLED",
        metadata_payload={"signal_reason": "MA_DEAD_CROSS"},
    )
    session = _mock_session(
        closed=[win, loss],
        exit_orders=[exit_order],
    )
    out = AutotradingPerformanceService(session).build(period="ALL")
    wl = out["win_loss"]
    assert wl["wins"] == 1
    assert wl["losses"] == 1


def test_open_position_included() -> None:
    open_b = StrategyPositionBindingEntity(
        binding_id=3,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=100,
        symbol="KRW-SUI",
        status=BINDING_STATUS_OPEN,
        ownership_code=OWNERSHIP_STRATEGY,
        owned_quantity=Decimal("10"),
        entry_price=Decimal("5000"),
        realized_pnl=Decimal("0"),
        fees=Decimal("5"),
        opened_at=datetime.now(timezone.utc),
    )
    session = _mock_session(open_bindings=[open_b])
    out = AutotradingPerformanceService(session).build(period="ALL")
    assert len(out["open_positions"]) == 1
    assert out["summary"]["open_position_count"] == 1
