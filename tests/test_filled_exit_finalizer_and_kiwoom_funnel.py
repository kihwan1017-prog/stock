"""FILLED exit → binding close finalizer regression (no broker calls)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.broker.upbit.filled_exit_finalizer import (
    detect_filled_exit_with_open_binding,
    dry_run_ghost_reconciliation,
    finalize_filled_exit,
    is_protective_or_auto_exit_sell,
    resolve_strategy_id_for_exit,
)
from stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync import (
    _is_auto_exit_sell,
    _load_auto_orders,
)
from stock_platform.position.exit_monitor import (
    ManagedPosition,
    PositionExitMonitorService,
)


def _exit_sell(**over) -> SimpleNamespace:
    base = dict(
        order_id=1863,
        side_code="SELL",
        status_code="FILLED",
        symbol="KRW-SUI",
        broker_code="UPBIT",
        user_broker_account_id=1380,
        strategy_id=None,
        strategy_deployment_id=None,
        filled_quantity=Decimal("9.19"),
        average_fill_price=Decimal("1085"),
        broker_order_id="uuid-sui",
        filled_at=datetime.now(timezone.utc),
        order_source="EXIT",
        metadata_payload={
            "source": "POSITION_EXIT_MONITOR",
            "exit_reason": "TRAILING_STOP",
            "upbit_paid_fee": "4.99",
        },
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_is_protective_exit_sell_detects_trailing() -> None:
    assert is_protective_or_auto_exit_sell(_exit_sell()) is True


def test_is_auto_exit_sell_includes_exit_monitor() -> None:
    assert _is_auto_exit_sell(_exit_sell()) is True


def test_load_auto_orders_includes_exit_source() -> None:
    session = MagicMock()
    exit_o = _exit_sell()
    auto_o = _exit_sell(
        order_id=1,
        order_source="AUTO",
        metadata_payload={
            "source": "REALTIME_SIGNAL",
            "signal_reason": "MA_DEAD_CROSS",
            "order_source": "AUTO",
        },
    )
    session.scalars.return_value = [exit_o, auto_o]
    out = _load_auto_orders(session, user_broker_account_id=1380, symbol="KRW-SUI")
    assert len(out) == 2


def test_resolve_strategy_id_from_open_binding() -> None:
    session = MagicMock()
    order = _exit_sell()
    binding = SimpleNamespace(strategy_id=17483)
    session.scalar.return_value = binding
    assert resolve_strategy_id_for_exit(session, order=order) == 17483


def test_finalize_filled_exit_calls_ensure_binding() -> None:
    session = MagicMock()
    order = _exit_sell()
    binding = SimpleNamespace(
        binding_id=31, status="CLOSED", strategy_id=17483, meta_json={}
    )
    with (
        patch(
            "stock_platform.broker.upbit.filled_exit_finalizer.resolve_strategy_id_for_exit",
            return_value=17483,
        ),
        patch(
            "stock_platform.broker.upbit.filled_exit_finalizer.stamp_strategy_id_on_order"
        ),
        patch(
            "stock_platform.broker.upbit.filled_exit_finalizer.upbit_fill_summary",
            create=True,
        ),
        patch(
            "stock_platform.risk_engine.strategy_owned_risk_service.StrategyOwnedRiskService"
        ) as svc_cls,
        patch(
            "stock_platform.operation.upbit_full_market.service.UpbitFullMarketAssignmentService"
        ) as fm_cls,
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync.reconcile_portfolio_slot_lifecycle"
        ) as recon,
        patch(
            "stock_platform.operation.upbit_full_market.constants.is_full_market_portfolio",
            return_value=True,
        ),
        patch(
            "stock_platform.broker.upbit.order_status.upbit_fill_summary",
            return_value={
                "executed_volume": Decimal("9.19"),
                "avg_price": Decimal("1085"),
                "paid_fee": Decimal("4.99"),
            },
        ),
    ):
        svc = svc_cls.return_value
        svc.ensure_binding_from_fill.return_value = binding
        fm_cls.return_value.get_or_create.return_value = SimpleNamespace(
            mode="FULL_MARKET_PORTFOLIO"
        )
        out = finalize_filled_exit(session, order=order, remote={}, actor="TEST")
    assert out["ok"] is True
    assert out["binding_status"] == "CLOSED"
    svc.ensure_binding_from_fill.assert_called_once()
    kwargs = svc.ensure_binding_from_fill.call_args.kwargs
    assert kwargs["side"] == "SELL"
    assert kwargs["exit_order_id"] == 1863
    assert kwargs["strategy_id"] == 17483
    recon.assert_called_once()


def test_finalize_idempotent_duplicate_fill() -> None:
    """ensure_binding_from_fill already idempotent on exit_order_id — call twice."""

    session = MagicMock()
    order = _exit_sell()
    binding = SimpleNamespace(
        binding_id=31, status="CLOSED", strategy_id=17483, meta_json={}
    )
    with (
        patch(
            "stock_platform.broker.upbit.filled_exit_finalizer.resolve_strategy_id_for_exit",
            return_value=17483,
        ),
        patch(
            "stock_platform.broker.upbit.filled_exit_finalizer.stamp_strategy_id_on_order"
        ),
        patch(
            "stock_platform.risk_engine.strategy_owned_risk_service.StrategyOwnedRiskService"
        ) as svc_cls,
        patch(
            "stock_platform.operation.upbit_full_market.constants.is_full_market_portfolio",
            return_value=False,
        ),
        patch(
            "stock_platform.broker.upbit.order_status.upbit_fill_summary",
            return_value={
                "executed_volume": Decimal("9.19"),
                "avg_price": Decimal("1085"),
                "paid_fee": Decimal("4.99"),
            },
        ),
    ):
        svc = svc_cls.return_value
        svc.ensure_binding_from_fill.return_value = binding
        a = finalize_filled_exit(session, order=order, actor="T1")
        b = finalize_filled_exit(session, order=order, actor="T2")
    assert a["ok"] and b["ok"]
    assert svc.ensure_binding_from_fill.call_count == 2


def test_exit_monitor_stamps_strategy_id() -> None:
    session = MagicMock()
    binding = SimpleNamespace(strategy_id=17483)
    session.scalar.return_value = binding
    session.scalars.return_value = []
    monitor = PositionExitMonitorService(session)
    fake = MagicMock()
    fake.submit.return_value = SimpleNamespace(
        allowed=True, order_id=999, reason_code="OK", outbox_id=1
    )
    monitor._execution = fake
    pos = ManagedPosition(
        account_id=0,
        exchange_code="UPBIT",
        symbol="KRW-SUI",
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("90"),
        highest_price=Decimal("110"),
        stop_loss_price=Decimal("95"),
        take_profit_price=Decimal("120"),
        trailing_stop_ratio=Decimal("0.03"),
        broker_code="UPBIT",
        user_broker_account_id=1380,
        owner_user_id=61,
        environment="LIVE",
    )
    with patch(
        "stock_platform.position.exit_monitor_live.has_blocking_live_exit_sell",
        return_value=False,
    ), patch(
        "stock_platform.position.smoke_exit_isolation.is_exit_submission_suppressed_for_smoke",
        return_value=None,
    ):
        monitor._submit_live_exit(
            position=pos,
            reason="TRAILING_STOP",
            trigger_price=Decimal("90"),
            skip_risk_checks=False,
        )
    cmd = fake.submit.call_args.args[0]
    assert cmd.strategy_id == 17483
    assert cmd.metadata_payload.get("strategy_id") == 17483
    assert cmd.metadata_payload.get("exit_reason") == "TRAILING_STOP"


def test_detect_ghost_open_binding() -> None:
    session = MagicMock()
    binding = SimpleNamespace(
        binding_id=31,
        user_broker_account_id=1380,
        symbol="KRW-SUI",
        entry_order_id=1862,
        owned_quantity=Decimal("9.19"),
        strategy_id=17483,
    )
    sell = _exit_sell()
    buy = SimpleNamespace(
        order_id=1862,
        status_code="FILLED",
        filled_at=datetime(2026, 8, 25, 18, 52, tzinfo=timezone.utc),
        created_at=datetime(2026, 8, 25, 18, 52, tzinfo=timezone.utc),
    )
    session.scalars.side_effect = [[binding], [sell]]
    session.get.return_value = buy
    out = detect_filled_exit_with_open_binding(session, user_broker_account_id=1380)
    assert out["count"] == 1
    assert out["symbols"] == ["KRW-SUI"]


def test_dry_run_safe_when_linkage_clear() -> None:
    session = MagicMock()
    item = {
        "binding_id": 31,
        "symbol": "KRW-SUI",
        "user_broker_account_id": 1380,
        "entry_order_id": 1862,
        "sell_order_id": 1863,
        "exit_reason": "TRAILING_STOP",
        "owned_quantity": "9.19",
    }
    buy = SimpleNamespace(status_code="FILLED")
    sell = _exit_sell()
    with patch(
        "stock_platform.broker.upbit.filled_exit_finalizer.detect_filled_exit_with_open_binding",
        return_value={"items": [item]},
    ):
        session.get.side_effect = lambda cls, oid: buy if oid == 1862 else sell
        session.scalars.return_value = []
        session.execute.return_value.first.return_value = (Decimal("0"),)
        out = dry_run_ghost_reconciliation(session, user_broker_account_id=1380)
    assert out["safe_count"] == 1
    assert out["decisions"][0]["verdict"] == "SAFE_TO_CLOSE"


def test_kiwoom_funnel_first_zero_activation() -> None:
    from stock_platform.trading.kiwoom_funnel_observability import (
        build_kiwoom_funnel_snapshot,
    )

    session = MagicMock()
    uba = SimpleNamespace(
        broker_code="KIWOOM",
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc),
    )
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.kiwoom_funnel_observability._resolve_fixed_symbols",
            return_value=["034310"],
        ),
        patch(
            "stock_platform.broker.live_transition_service.LiveTradingTransitionService"
        ) as act_cls,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveUnattendedAuthorizationService"
        ) as un_cls,
        patch(
            "stock_platform.trading.upbit_24x7_control.combined_control_status",
            return_value={"strategy_runtime": "STOPPED"},
        ),
        patch.object(
            __import__(
                "stock_platform.realtime.kiwoom_market_realtime_runtime",
                fromlist=["kiwoom_market_realtime_runtime"],
            ).kiwoom_market_realtime_runtime,
            "status",
            return_value={"running": False, "connected": False},
        ),
        patch(
            "stock_platform.trading.kiwoom_trading_day_lifecycle.KiwoomTradingDayLifecycleService"
        ) as life_cls,
        patch(
            "stock_platform.trading.market_hours_authorization.krx_market_hours_state",
            return_value={
                "in_regular_session": True,
                "is_trading_day": True,
                "past_close": False,
                "before_open": False,
                "session_type": "REGULAR",
                "reason_code": "CALENDAR_OPEN",
            },
        ),
    ):
        act_cls.return_value.peek_active.return_value = None
        un_cls.return_value.status_dict.return_value = {
            "entry_authorized": False,
            "next_trading_day_auto_start": True,
        }
        life_cls.return_value.status_dict.return_value = {"phase": "WAITING"}
        session.scalars.return_value = []
        out = build_kiwoom_funnel_snapshot(session, user_broker_account_id=1381)
    assert out["FIRST_ZERO_STAGE"] == "ACTIVATION_INACTIVE"
    assert out["universe"]["034310_ONLY"] is True
    assert out["signal_semantics"]["NEW_CROSS_REQUIRED"] is True
    assert out["signal_semantics"]["STRATEGY_CHANGED"] is False
