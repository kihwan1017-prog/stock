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
    assert classify_exit_reason("MA_DEAD_CROSS") == "MA_DEAD_CROSS"
    assert classify_exit_reason("STOP_LOSS") == "STOP_LOSS"
    assert classify_exit_reason("TAKE_PROFIT") == "TAKE_PROFIT"
    assert classify_exit_reason("TRAILING_STOP") == "TRAILING_STOP"
    assert classify_exit_reason("MAX_HOLD_TIME") == "MAX_HOLD_TIME"


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
    assert m["exit_reason_category"] == "MA_DEAD_CROSS"
    net = Decimal(str(m["net_pnl"]))
    assert net == Decimal("38.21")
    cost = Decimal(str(m["entry_cost"]))
    assert cost > Decimal("0")
    ret = Decimal(str(m["return_pct"]))
    assert ret > Decimal("0")


def test_period_date_window_kst_and_fees_in_net() -> None:
    """KST date window + NET = GROSS - FEES consistency."""

    from zoneinfo import ZoneInfo

    from stock_platform.operation.autotrading_performance_service import (
        resolve_period_window,
    )

    kst = ZoneInfo("Asia/Seoul")
    start_utc, end_excl, start_d, end_d = resolve_period_window(
        start_date="2026-09-04",
        end_date="2026-09-04",
        today=datetime(2026, 9, 4, tzinfo=kst).date(),
    )
    assert start_d.isoformat() == "2026-09-04"
    assert end_d.isoformat() == "2026-09-04"
    assert start_utc is not None and end_excl is not None
    assert (end_excl - start_utc).total_seconds() == 24 * 3600

    closed_at = datetime(2026, 9, 4, 12, 0, tzinfo=kst).astimezone(timezone.utc)
    win = StrategyPositionBindingEntity(
        binding_id=201,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=100,
        symbol="KRW-AAA",
        status=BINDING_STATUS_CLOSED,
        ownership_code=OWNERSHIP_STRATEGY,
        owned_quantity=Decimal("0"),
        entry_price=Decimal("100"),
        realized_pnl=Decimal("20"),  # gross
        fees=Decimal("3"),
        closed_at=closed_at,
        meta_json={"exit_fill_price": "120", "closed_quantity": "1"},
    )
    session = _mock_session(closed=[win])
    out = AutotradingPerformanceService(session).build(
        period="TODAY",
        start_date="2026-09-04",
        end_date="2026-09-04",
        user_broker_account_id=1380,
    )
    s = out["summary"]
    assert Decimal(str(s["period_gross_pnl"])) == Decimal("20.00")
    assert Decimal(str(s["period_fees"])) == Decimal("3.00")
    assert Decimal(str(s["period_net_pnl"])) == Decimal("17.00")
    assert abs(Decimal(str(s["period_gross_minus_fees_delta"]))) <= Decimal("0.01")
    assert len(out["symbol_performance"]) == 1
    row = out["symbol_performance"][0]
    assert row["symbol"] == "KRW-AAA"
    assert Decimal(str(row["net_pnl"])) == Decimal("17.00")

    session2 = _mock_session(closed=[win])
    detail = AutotradingPerformanceService(session2).build_symbol_detail(
        symbol="KRW-AAA",
        start_date="2026-09-04",
        end_date="2026-09-04",
        user_broker_account_id=1380,
    )
    assert detail["totals"]["round_trip_count"] == 1
    assert len(detail["daily"]) == 1
    assert len(detail["trades"]) == 1


def test_max_period_clamped_to_90_days() -> None:
    from stock_platform.operation.autotrading_performance_service import (
        resolve_period_window,
    )

    start_utc, end_excl, start_d, end_d = resolve_period_window(
        start_date="2026-01-01",
        end_date="2026-09-04",
        today=datetime(2026, 9, 4, tzinfo=timezone.utc).date(),
        max_days=90,
    )
    assert (end_d - start_d).days <= 90
    assert start_utc is not None and end_excl is not None


def _mock_session(
    *,
    closed: list | None = None,
    open_bindings: list | None = None,
    exit_orders: list | None = None,
    snapshots: list | None = None,
    today_orders: list | None = None,
) -> MagicMock:
    """scalars 호출 순서: CLOSED → OPEN → exit orders → mark prices → today orders."""

    session = MagicMock()
    queues = [
        iter(closed or []),
        iter(open_bindings or []),
        iter(exit_orders or []),
        iter(snapshots or []),
        iter(today_orders or []),
    ]

    def _scalars(_stmt):  # noqa: ANN001
        if queues:
            return queues.pop(0)
        return iter([])

    session.scalars = MagicMock(side_effect=_scalars)
    return session


def test_today_profit_loss_amounts_match_net() -> None:
    """오늘 수익/손실 합 = 순손익 (canonical net_pnl)."""

    from zoneinfo import ZoneInfo

    kst = ZoneInfo("Asia/Seoul")
    now = datetime.now(kst)
    closed_at = datetime(
        now.year, now.month, now.day, 12, 0, tzinfo=kst
    ).astimezone(timezone.utc)

    win = StrategyPositionBindingEntity(
        binding_id=101,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=100,
        symbol="KRW-WIN",
        status=BINDING_STATUS_CLOSED,
        ownership_code=OWNERSHIP_STRATEGY,
        owned_quantity=Decimal("0"),
        entry_price=Decimal("100"),
        realized_pnl=Decimal("15"),
        fees=Decimal("0"),
        closed_at=closed_at,
        meta_json={"exit_fill_price": "115", "closed_quantity": "1"},
    )
    loss = StrategyPositionBindingEntity(
        binding_id=102,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=100,
        symbol="KRW-LOSS",
        status=BINDING_STATUS_CLOSED,
        ownership_code=OWNERSHIP_STRATEGY,
        owned_quantity=Decimal("0"),
        entry_price=Decimal("100"),
        realized_pnl=Decimal("-5"),
        fees=Decimal("0"),
        closed_at=closed_at,
        meta_json={"exit_fill_price": "95", "closed_quantity": "1"},
    )
    session = _mock_session(closed=[win, loss])
    out = AutotradingPerformanceService(session).build(period="TODAY")
    s = out["summary"]
    assert Decimal(str(s["today_profit_amount"])) == Decimal("15.00")
    assert Decimal(str(s["today_loss_amount"])) == Decimal("-5.00")
    assert Decimal(str(s["today_net_pnl"])) == Decimal("10.00")
    assert Decimal(str(s["today_realized_pnl"])) == Decimal("10.00")
    assert s["today_wins"] == 1
    assert s["today_losses"] == 1
    assert out["today_order_activity"]["buy_count"] == 0
    assert len(out["today_hourly_pnl"]) == 24


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


def test_period_90d_filters_old_trades() -> None:
    recent = _geod_closed_binding()
    old = StrategyPositionBindingEntity(
        binding_id=9,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=100,
        symbol="KRW-OLD",
        status=BINDING_STATUS_CLOSED,
        ownership_code=OWNERSHIP_STRATEGY,
        owned_quantity=Decimal("0"),
        entry_price=Decimal("100"),
        realized_pnl=Decimal("5"),
        fees=Decimal("0"),
        opened_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        closed_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        meta_json={"exit_fill_price": "105", "closed_quantity": "1"},
    )
    session = _mock_session(closed=[recent, old])
    out = AutotradingPerformanceService(session).build(period="90D")
    assert out["period"] == "90D"
    assert out["closed_trade_count"] == 1
    assert out["recent_closed_trades"][0]["symbol"] == "KRW-GEOD"


def test_broker_upbit_filters_kiwoom() -> None:
    """broker 필터는 DB 쿼리 단계 — mock은 UPBIT 행만 반환한다고 가정."""
    upbit = _geod_closed_binding()
    session = _mock_session(closed=[upbit])
    out = AutotradingPerformanceService(session).build(broker="UPBIT", period="ALL")
    assert out["broker"] == "UPBIT"
    assert out["closed_trade_count"] == 1
    assert out["recent_closed_trades"][0]["broker_code"] == "UPBIT"
    assert out["daily_by_broker"] == []
    assert out["cumulative_by_broker"] == []


def test_broker_kiwoom_only() -> None:
    kiwoom = StrategyPositionBindingEntity(
        binding_id=11,
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        strategy_id=100,
        symbol="005930",
        status=BINDING_STATUS_CLOSED,
        ownership_code=OWNERSHIP_STRATEGY,
        owned_quantity=Decimal("0"),
        entry_price=Decimal("70000"),
        realized_pnl=Decimal("500"),
        fees=Decimal("50"),
        closed_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        meta_json={"exit_fill_price": "70500", "closed_quantity": "1"},
    )
    session = _mock_session(closed=[kiwoom])
    out = AutotradingPerformanceService(session).build(broker="KIWOOM", period="ALL")
    assert out["broker"] == "KIWOOM"
    assert out["closed_trade_count"] == 1
    assert out["recent_closed_trades"][0]["broker_code"] == "KIWOOM"


def test_broker_all_includes_broker_series() -> None:
    upbit = _geod_closed_binding()
    session = _mock_session(closed=[upbit])
    out = AutotradingPerformanceService(session).build(broker="ALL", period="30D")
    assert out["broker"] == "ALL"
    assert isinstance(out["daily_by_broker"], list)
    assert isinstance(out["cumulative_by_broker"], list)
    assert len(out["broker_comparison"]) == 2


def test_holding_return_shape() -> None:
    binding = _geod_closed_binding()
    exit_order = TradingOrderEntity(
        order_id=1801,
        client_order_id="c-exit",
        symbol="KRW-GEOD",
        side_code="SELL",
        status_code="FILLED",
        metadata_payload={"signal_reason": "MA_DEAD_CROSS"},
    )
    session = _mock_session(closed=[binding], exit_orders=[exit_order])
    out = AutotradingPerformanceService(session).build(period="ALL")
    assert len(out["holding_return"]) == 1
    row = out["holding_return"][0]
    assert row["symbol"] == "KRW-GEOD"
    assert row["duration_sec"] is not None
    assert Decimal(str(row["return_pct"])) > Decimal("0")


def test_single_trade_low_sample_message() -> None:
    binding = _geod_closed_binding()
    session = _mock_session(closed=[binding])
    out = AutotradingPerformanceService(session).build(period="30D")
    assert out["closed_trade_count"] == 1
    assert out["low_sample_warning"] is True
    assert out["low_sample_message"] is not None
    assert "1건" in out["low_sample_message"]


def test_include_ops_returns_ops_insight(monkeypatch) -> None:
    from stock_platform.operation.upbit_full_market import portfolio_entry_signal

    monkeypatch.setattr(
        portfolio_entry_signal.portfolio_entry_telemetry,
        "snapshot",
        lambda _uba: {
            "KRW-TEST": {
                "evaluation_count": 10,
                "last_decision": "BLOCK",
                "last_block_reason": "RSI_TOO_HIGH",
            }
        },
    )

    class _Policy:
        max_positions = 5

    session = MagicMock()

    def _scalar(_stmt):  # noqa: ANN001
        return _Policy()

    closed = _geod_closed_binding()
    session.scalar = MagicMock(side_effect=_scalar)
    queues = [
        iter([closed]),
        iter([]),
        iter([]),
        iter([]),
        iter([]),  # today_order_activity
        iter([]),
        iter([]),
        iter([]),
    ]

    def _scalars(_stmt):  # noqa: ANN001
        if queues:
            return queues.pop(0)
        return iter([])

    session.scalars = MagicMock(side_effect=_scalars)

    out = AutotradingPerformanceService(session).build(
        broker="UPBIT", period="7D", include_ops=True
    )
    assert out["ops_insight"] is not None
    pipeline = out["ops_insight"]["pipeline"]
    assert pipeline.get("slots_capacity") == 5
    blockers = out["ops_insight"]["entry_blockers"]
    assert len(blockers) >= 1
    assert blockers[0]["reason_code"] == "RSI_TOO_HIGH"
