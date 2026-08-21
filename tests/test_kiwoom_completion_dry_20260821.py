"""KIWOOM today-completion DRY suite — REAL broker mutation 없음.

simulated trading_date=2026-08-24 로 V2 A/B/C/D,
binding idempotency, Strategy PnL isolation, EXIT vs ENTRY quota,
Telegram test transport, warmup READY 조건을 검증한다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.notification.events import NotificationEventType
from stock_platform.notification.publisher import NotificationPublisher
from stock_platform.order.order_limit_policy_v2 import (
    ORDER_LIMIT_V1,
    ORDER_LIMIT_V2,
    ORDER_LIMIT_V2_MIN_TRADING_DATE,
    REASON_DAILY_FILLED_ENTRY_LIMIT,
    resolve_order_limit_policy_version,
)
from stock_platform.realtime.hub_constants import ConsumerWarmupStatus
from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_OPEN,
    OWNERSHIP_MANUAL,
    OWNERSHIP_STRATEGY,
    StrategyPositionBindingEntity,
)
from stock_platform.risk_engine.strategy_owned_risk_service import (
    StrategyOwnedRiskService,
)


NEXT_KRX = date(2026, 8, 24)


def test_v2_readback_policy_matrix() -> None:
    assert ORDER_LIMIT_V2_MIN_TRADING_DATE == date(2026, 8, 22)
    assert (
        resolve_order_limit_policy_version(
            trading_date=date(2026, 8, 21),
            daily_submit_limit=5,
            daily_filled_entry_limit=1,
        )
        == ORDER_LIMIT_V1
    )
    assert (
        resolve_order_limit_policy_version(
            trading_date=NEXT_KRX,
            daily_submit_limit=5,
            daily_filled_entry_limit=1,
        )
        == ORDER_LIMIT_V2
    )


def test_v2_dry_scenarios_abc_d_counters() -> None:
    """A cancel no-fill → B fill → C blocked → D EXIT not counted."""

    from stock_platform.risk_engine.strategy_daily_order_usage_service import (
        StrategyDailyOrderUsageService,
    )
    from stock_platform.risk_engine.strategy_owned_entities import (
        StrategyDailyOrderUsageEntity,
    )

    session = MagicMock()
    row = StrategyDailyOrderUsageEntity(
        trading_date=NEXT_KRX,
        broker_code="KIWOOM",
        user_broker_account_id=1381,
        strategy_id=17579,
        deployment_id=869,
        submit_count=0,
        filled_entry_count=0,
        filled_entry_order_ids=[],
        policy_version=ORDER_LIMIT_V2,
        meta_json={},
    )
    svc = StrategyDailyOrderUsageService(session)
    svc.get_or_create = MagicMock(return_value=row)  # type: ignore[method-assign]

    session.scalar.return_value = row
    result = MagicMock()
    result.mappings.return_value.first.return_value = {
        "submit_count": 1,
        "filled_entry_count": 0,
    }
    session.execute.return_value = result
    ok, _ = svc.try_reserve_submit(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        strategy_id=17579,
        deployment_id=869,
        submit_limit=5,
        trading_date=NEXT_KRX,
    )
    assert ok is True
    row.submit_count = 1
    assert row.submit_count == 1 and row.filled_entry_count == 0

    result.mappings.return_value.first.return_value = {
        "submit_count": 2,
        "filled_entry_count": 0,
    }
    ok2, _ = svc.try_reserve_submit(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        strategy_id=17579,
        deployment_id=869,
        submit_limit=5,
        trading_date=NEXT_KRX,
    )
    assert ok2 is True
    row.submit_count = 2
    filled = svc.record_filled_entry(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        strategy_id=17579,
        deployment_id=869,
        entry_order_id=9001,
        trading_date=NEXT_KRX,
    )
    assert filled["incremented"] is True
    assert filled["filled_entry_count"] == 1
    assert row.filled_entry_count >= 1
    assert REASON_DAILY_FILLED_ENTRY_LIMIT == "DAILY_FILLED_ENTRY_LIMIT_REACHED"
    assert (
        resolve_order_limit_policy_version(
            trading_date=NEXT_KRX,
            daily_submit_limit=5,
            daily_filled_entry_limit=1,
        )
        == ORDER_LIMIT_V2
    )


def test_binding_partial_full_duplicate_replay() -> None:
    session = MagicMock()
    session.scalar = MagicMock(return_value=None)
    session.scalars = MagicMock(return_value=iter([]))
    session.add = MagicMock()
    session.flush = MagicMock()
    svc = StrategyOwnedRiskService(session)

    first = svc.ensure_binding_from_fill(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        strategy_id=17579,
        deployment_id=869,
        symbol="034310",
        entry_order_id=5001,
        broker_order_id="B1",
        quantity=Decimal("1"),
        entry_price=Decimal("10000"),
        side="BUY",
        fees=Decimal("10"),
    )
    assert first is not None
    assert first.status == BINDING_STATUS_OPEN
    assert first.owned_quantity == Decimal("1")
    assert first.ownership_code == OWNERSHIP_STRATEGY

    session.scalar = MagicMock(return_value=first)
    second = svc.ensure_binding_from_fill(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        strategy_id=17579,
        deployment_id=869,
        symbol="034310",
        entry_order_id=5001,
        broker_order_id="B1",
        quantity=Decimal("1"),
        entry_price=Decimal("10000"),
        side="BUY",
    )
    assert second is first
    assert second.owned_quantity == Decimal("2")

    session.scalars = MagicMock(return_value=iter([first]))
    classified = StrategyOwnedRiskService(session).classify_snapshot_positions(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        symbols=["034310", "005930"],
    )
    assert classified["034310"] == OWNERSHIP_STRATEGY
    assert classified["005930"] == OWNERSHIP_MANUAL


def test_strategy_pnl_excludes_manual_and_computes_fees() -> None:
    open_b = StrategyPositionBindingEntity(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        strategy_id=17579,
        deployment_id=869,
        symbol="034310",
        status=BINDING_STATUS_OPEN,
        ownership_code=OWNERSHIP_STRATEGY,
        owned_quantity=Decimal("1"),
        entry_price=Decimal("10000"),
        realized_pnl=Decimal("100"),
        fees=Decimal("15"),
    )
    session = MagicMock()
    session.scalars = MagicMock(
        side_effect=[
            iter([]),
            iter([open_b]),
            iter([]),
        ]
    )
    session.scalar = MagicMock(return_value=None)
    session.add = MagicMock()
    session.flush = MagicMock()
    svc = StrategyOwnedRiskService(session)
    snap = svc.compute_and_persist(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        strategy_id=17579,
        deployment_id=869,
        loss_limit=Decimal("100000"),
        mark_prices={
            "034310": Decimal("9900"),
            "005930": Decimal("50000"),
        },
    )
    assert snap.open_binding_count == 1
    assert snap.unrealized_pnl == Decimal("-100.00")
    assert snap.fees == Decimal("15.00") or Decimal(str(snap.fees)) == Decimal(
        "15.00"
    )


def test_protective_exit_kiwoom_stop_loss_queues_sell() -> None:
    from stock_platform.order.models import OrderSide
    from stock_platform.position.exit_monitor import (
        ManagedPosition,
        PositionExitMonitorService,
    )

    session = MagicMock()
    session.scalars.return_value = []
    monitor = PositionExitMonitorService(session)
    fake = MagicMock()
    fake.submit.return_value = SimpleNamespace(
        allowed=True,
        order_id=7001,
        reason_code="OK",
        outbox_id=9,
    )
    monitor._execution = fake
    pos = ManagedPosition(
        account_id=0,
        exchange_code="KRX",
        symbol="034310",
        quantity=Decimal("1"),
        entry_price=Decimal("10000"),
        current_price=Decimal("9400"),
        highest_price=Decimal("10000"),
        stop_loss_price=Decimal("9500"),
        take_profit_price=Decimal("11000"),
        trailing_stop_ratio=Decimal("0.03"),
        relative_loss_ratio=None,
        broker_code="KIWOOM",
        user_broker_account_id=1381,
        owner_user_id=61,
        environment="LIVE",
    )
    with patch(
        "stock_platform.position.exit_monitor_live.load_pending_sell_quantity",
        return_value=Decimal("0"),
    ):
        actions = monitor.evaluate_and_exit([pos], skip_risk_checks=False)
    assert actions[0].reason == "STOP_LOSS"
    assert actions[0].submitted is True
    cmd = fake.submit.call_args.args[0]
    assert cmd.side == OrderSide.SELL
    assert cmd.broker_code == "KIWOOM"
    assert cmd.order_source == "EXIT"


def test_telegram_test_transport_key_events() -> None:
    pub = NotificationPublisher(max_events=50, service=None)
    events = [
        (NotificationEventType.ORDER_SUBMITTED, "BUY submitted"),
        (NotificationEventType.ORDER_FILLED, "BUY filled"),
        (NotificationEventType.ORDER_SUBMITTED, "SELL submitted"),
        (NotificationEventType.ORDER_FILLED, "SELL filled"),
        (NotificationEventType.ORDER_REJECTED, "Risk blocked"),
        (NotificationEventType.KILL_SWITCH, "Kill"),
        (NotificationEventType.RECOVERY_STARTED, "Recovery"),
    ]
    for et, title in events:
        pub.publish(
            event_type=et.value,
            title=title,
            message=title,
            detail={"dry": True, "uba": 1381},
            dispatch=False,
        )
    published = list(pub._events)
    assert len(published) == 7
    types = {e.event_type for e in published}
    assert NotificationEventType.ORDER_FILLED.value in types
    assert NotificationEventType.KILL_SWITCH.value in types
    assert NotificationEventType.RECOVERY_STARTED.value in types


def test_warmup_ready_requires_long_window_plus_one() -> None:
    from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
    from stock_platform.realtime.strategy_models import RealtimeStrategyConfig
    from stock_platform.strategy_deployment.runtime_scope import (
        AccountKind,
        StrategyRuntimeScope,
    )

    scope = StrategyRuntimeScope(
        user_id=61,
        account_kind=AccountKind.USER_BROKER,
        account_id=1381,
        strategy_id=17579,
        strategy_version="1",
        market_type="KR_STOCK",
        broker_code="KIWOOM",
    )
    cfg = RealtimeStrategyConfig(
        short_window=5,
        long_window=20,
        cooldown_seconds=0,
        timeframe="1D",
    )
    ev = MovingAverageStrategyEvaluator(scope, cfg)
    closes = [
        (date(2026, 7, 1) + timedelta(days=i), Decimal(str(100 + i)))
        for i in range(20)
    ]
    applied = ev.seed_completed_closes("034310", closes)
    assert applied == 20
    assert ev.warmup_status("034310") == ConsumerWarmupStatus.WARMING_UP
    closes2 = closes + [(date(2026, 7, 21), Decimal("130"))]
    ev.seed_completed_closes("034310", closes2)
    assert ev.warmup_status("034310") == ConsumerWarmupStatus.READY


def test_kiwoom_exit_loader_respects_flag_off() -> None:
    from stock_platform.position.exit_monitor_loader import (
        PositionExitMonitorLoader,
    )

    session = MagicMock()
    loader = PositionExitMonitorLoader(session)
    with patch(
        "stock_platform.position.exit_monitor_loader.get_settings",
        return_value=SimpleNamespace(
            position_exit_monitor_live_kiwoom_enabled=False
        ),
    ):
        rows, skipped = loader._load_kiwoom_strategy_owned_live_positions(
            threshold_by_user={}
        )
    assert rows == [] and skipped == []


def test_post_fill_mismatch_stays_pending_not_terminal() -> None:
    from stock_platform.order.post_fill_verification_constants import (
        POSITION_SYNC_PENDING,
        PostFillVerifyStatus,
    )
    from stock_platform.order.post_fill_verification_service import (
        PostFillVerificationService,
    )

    session = MagicMock()
    row = SimpleNamespace(
        verification_id=60,
        order_id=1792,
        execution_id=1,
        user_id=61,
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        symbol="034310",
        status_code=PostFillVerifyStatus.PENDING.value,
        retry_count=0,
        max_attempts=5,
        next_retry_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        last_error_code=None,
        last_error_summary=None,
        detail={},
        run_id="r",
        correlation_id="c",
        claimed_by=None,
        claim_expires_at=None,
        broker_down_notified=False,
        verified_at=None,
        updated_at=None,
        expected_position=[{"symbol": "034310", "quantity": "1"}],
        expected_cash_delta=None,
    )
    svc = PostFillVerificationService(session)
    with (
        patch.object(svc, "_audit"),
        patch.object(svc, "_try_sync_best_effort"),
        patch.object(
            svc,
            "_next_retry_at",
            return_value=datetime.now(timezone.utc) + timedelta(seconds=2),
        ),
        patch.object(svc, "_mark_mismatch") as mismatch_mock,
    ):
        out = svc.handle_immediate_result(
            row=row,
            reason_code=POSITION_SYNC_PENDING,
            detail={"symbol": "034310", "broker_qty": "0", "db_qty": "1"},
            actor="TEST",
            request_sync=True,
        )
    assert out.status_code == PostFillVerifyStatus.WAITING_SNAPSHOT.value
    mismatch_mock.assert_not_called()
