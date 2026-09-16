"""UPBIT 자동매매 LIVE E2E wiring — mock/spy (실 POST /v1/orders = 0)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.live_outbox_worker_runtime import (
    LiveOutboxWorkerRuntime,
)
from stock_platform.order.outbox_worker import OrderOutboxWorker
from stock_platform.realtime.autotrading_idempotency import (
    build_autotrading_idempotency_key,
)
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.live_runtime_control import live_auto_start_allowed
from stock_platform.realtime.risk_integrated_order_executor import (
    RiskIntegratedRealtimeOrderExecutor,
)
from stock_platform.realtime.safety_guard import RealtimeOrderSafetyGuard
from stock_platform.realtime.safety_models import RealtimeOrderSafetyConfig
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)


def _signal(**kwargs) -> RealtimeSignal:
    base = dict(
        exchange_code="UPBIT",
        symbol="KRW-XRP",
        action=RealtimeSignalAction.BUY,
        signal_price=Decimal("1450"),
        short_average=None,
        long_average=None,
        change_rate=None,
        reason_code="MA_GOLDEN_CROSS",
        generated_at=datetime(2026, 8, 8, 3, 0, tzinfo=timezone.utc),
        signal_id="sig-1",
        fingerprint="fp-abc123",
        scope_key="uba:1380:strategy:9",
        user_id=61,
        account_kind="USER_BROKER",
        account_id=1380,
        strategy_id=9,
        strategy_version="1",
        broker_code="UPBIT",
        market_type="CRYPTO",
    )
    base.update(kwargs)
    return RealtimeSignal(**base)


def test_idempotency_key_uses_signal_fingerprint() -> None:
    key = build_autotrading_idempotency_key(
        _signal(), user_broker_account_id=1380
    )
    assert key == "strategy:9:signal:fp-abc123:uba:1380"


def test_idempotency_stable_across_ticks() -> None:
    a = build_autotrading_idempotency_key(
        _signal(), user_broker_account_id=1380
    )
    b = build_autotrading_idempotency_key(
        _signal(
            generated_at=datetime(2026, 8, 8, 4, 0, tzinfo=timezone.utc)
        ),
        user_broker_account_id=1380,
    )
    assert a == b


def test_live_outbox_worker_disabled_by_default() -> None:
    runtime = LiveOutboxWorkerRuntime()
    result = runtime.start()
    assert result["started"] is False
    assert result["reason"] == "LIVE_OUTBOX_WORKER_DISABLED"


def test_outbox_worker_rejects_paper_and_live_only() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        OrderOutboxWorker(
            session_factory=MagicMock(),
            dispatcher=MagicMock(),
            worker_id="x",
            paper_only=True,
            live_only=True,
        )


def test_auto_signal_submits_one_order_with_fingerprint() -> None:
    session = MagicMock()
    # open position count = 0
    session.scalar.return_value = 0

    guard = RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            live_trading_enabled=True,
            live_unlock_token="UNLOCK",
            max_open_positions=5,
            duplicate_order_window_seconds=0,
            symbol_cooldown_seconds=0,
            max_orders_per_minute=100,
            enforce_market_hours_for_krx=False,
        )
    )
    cfg = RealtimeExecutionConfig(
        account_id=1,
        order_amount=Decimal("5000"),
        mode=RealtimeExecutionMode.LIVE,
        user_broker_account_id=1380,
        user_id=61,
    )
    executor = RiskIntegratedRealtimeOrderExecutor(
        session=session,
        execution_config=cfg,
        safety_guard=guard,
    )

    submit_result = SimpleNamespace(
        allowed=True,
        reason_code="QUEUED",
        order_id=9001,
        outbox_id=8001,
        status_code="PENDING",
        client_order_id="c1",
        quantity=Decimal("3.4"),
        price=Decimal("1450"),
    )

    with (
        patch.object(
            executor,
            "_resolve_account_number",
            return_value="uba-1380",
        ),
        patch(
            "stock_platform.realtime.risk_integrated_order_executor.PersistentKillSwitchGuard"
        ) as kill_cls,
        patch(
            "stock_platform.broker.recovery_lock.RecoveryAccountLockService"
        ) as lock_cls,
        patch(
            "stock_platform.realtime.risk_integrated_order_executor.DatabaseBackedRiskOrderGuard"
        ) as risk_cls,
        patch(
            "stock_platform.realtime.risk_integrated_order_executor.OrderExecutionService"
        ) as oes_cls,
        patch(
            "stock_platform.order.live_dry_run.is_live_dry_run_mode",
            return_value=False,
        ),
        patch(
            "stock_platform.order.live_shadow.is_live_shadow_mode",
            return_value=False,
        ),
    ):
        kill_cls.return_value.require_order_allowed.return_value = None
        lock_cls.return_value.is_trading_paused.return_value = False
        risk_cls.return_value.check.return_value = SimpleNamespace(
            allowed=True, blocked_reason=None
        )
        oes_cls.return_value.submit.return_value = submit_result

        first = executor.execute(_signal())

    assert first.order_id == 9001
    assert oes_cls.return_value.submit.call_count == 1
    cmd = oes_cls.return_value.submit.call_args.args[0]
    assert cmd.idempotency_key == "strategy:9:signal:fp-abc123:uba:1380"
    assert cmd.user_broker_account_id == 1380
    assert cmd.order_source == "AUTO"
    assert cmd.environment == "LIVE"
    assert cmd.metadata_payload["source_signal_fingerprint"] == "fp-abc123"
    assert cmd.broker_code == "UPBIT"
    # LIVE Risk XOR — paper account_id 미전달
    risk_kwargs = risk_cls.return_value.check.call_args.kwargs
    assert risk_kwargs["account_id"] is None
    assert risk_kwargs["user_broker_account_id"] == 1380

def test_duplicate_signal_uses_stable_idempotency_key() -> None:
    """동일 fingerprint → 동일 idempotency_key (OES 중복 차단 전제)."""

    a = build_autotrading_idempotency_key(
        _signal(), user_broker_account_id=1380
    )
    b = build_autotrading_idempotency_key(
        _signal(
            generated_at=datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)
        ),
        user_broker_account_id=1380,
    )
    assert a == b == "strategy:9:signal:fp-abc123:uba:1380"


def test_fail_closed_live_off_at_outbox_assert() -> None:
    from stock_platform.order.outbox_worker import OrderOutboxWorker

    session = MagicMock()
    uba = SimpleNamespace(
        is_active=True,
        broker_code="UPBIT",
        user_id=61,
        live_order_enabled=False,
        live_armed=False,
    )
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as guard_cls,
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService"
        ) as arm_cls,
    ):
        guard_cls.return_value.require_active.return_value = None
        arm_cls.return_value.expire_if_needed.return_value = False
        with pytest.raises(PermissionError) as exc:
            OrderOutboxWorker._assert_live_dispatch_allowed(
                session,
                {
                    "environment": "LIVE",
                    "broker_code": "UPBIT",
                    "user_broker_account_id": 1380,
                    "owner_user_id": 61,
                },
                outbox_id=None,
            )
    assert "LIVE_ORDER_DISABLED" in str(exc.value)


def test_fail_closed_arm_off_at_outbox_assert() -> None:
    from stock_platform.order.outbox_worker import OrderOutboxWorker

    session = MagicMock()
    uba = SimpleNamespace(
        is_active=True,
        broker_code="UPBIT",
        user_id=61,
        live_order_enabled=True,
        live_armed=False,
    )
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as guard_cls,
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService"
        ) as arm_cls,
    ):
        guard_cls.return_value.require_active.return_value = None
        arm_cls.return_value.expire_if_needed.return_value = False
        with pytest.raises(PermissionError) as exc:
            OrderOutboxWorker._assert_live_dispatch_allowed(
                session,
                {
                    "environment": "LIVE",
                    "broker_code": "UPBIT",
                    "user_broker_account_id": 1380,
                    "owner_user_id": 61,
                },
                outbox_id=None,
            )
    assert "LIVE_NOT_ARMED" in str(exc.value)


def test_kill_switch_blocks_auto_buy() -> None:
    session = MagicMock()
    session.scalar.return_value = 0
    guard = RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            live_trading_enabled=True,
            live_unlock_token="UNLOCK",
            enforce_market_hours_for_krx=False,
        )
    )
    executor = RiskIntegratedRealtimeOrderExecutor(
        session=session,
        execution_config=RealtimeExecutionConfig(
            account_id=1,
            order_amount=Decimal("5000"),
            mode=RealtimeExecutionMode.LIVE,
            user_broker_account_id=1380,
        ),
        safety_guard=guard,
    )
    with (
        patch.object(executor, "_resolve_account_number", return_value="x"),
        patch(
            "stock_platform.realtime.risk_integrated_order_executor.PersistentKillSwitchGuard"
        ) as kill_cls,
        patch(
            "stock_platform.broker.recovery_lock.RecoveryAccountLockService"
        ) as lock_cls,
        patch(
            "stock_platform.realtime.risk_integrated_order_executor.OrderExecutionService"
        ) as oes_cls,
    ):
        lock_cls.return_value.is_trading_paused.return_value = False
        kill_cls.return_value.require_order_allowed.side_effect = (
            PermissionError("KILL")
        )
        result = executor.execute(_signal())
    assert result.order_id is None
    assert result.reason_code == "GLOBAL_KILL_SWITCH_ACTIVE"
    oes_cls.assert_not_called()


def test_account_paused_blocks_auto_buy() -> None:
    session = MagicMock()
    session.scalar.return_value = 0
    executor = RiskIntegratedRealtimeOrderExecutor(
        session=session,
        execution_config=RealtimeExecutionConfig(
            account_id=1,
            order_amount=Decimal("5000"),
            mode=RealtimeExecutionMode.LIVE,
            user_broker_account_id=1380,
        ),
        safety_guard=RealtimeOrderSafetyGuard(
            RealtimeOrderSafetyConfig(
                live_trading_enabled=True,
                live_unlock_token="UNLOCK",
                enforce_market_hours_for_krx=False,
            )
        ),
    )
    with (
        patch.object(executor, "_resolve_account_number", return_value="x"),
        patch(
            "stock_platform.broker.recovery_lock.RecoveryAccountLockService"
        ) as lock_cls,
        patch(
            "stock_platform.realtime.risk_integrated_order_executor.OrderExecutionService"
        ) as oes_cls,
    ):
        lock_cls.return_value.is_trading_paused.return_value = True
        result = executor.execute(_signal())
    assert result.reason_code == "ACCOUNT_PAUSED"
    oes_cls.assert_not_called()


def test_sell_path_uses_auto_idempotency() -> None:
    key = build_autotrading_idempotency_key(
        _signal(
            action=RealtimeSignalAction.SELL,
            fingerprint="fp-sell",
            reason_code="MA_DEAD_CROSS",
        ),
        user_broker_account_id=1380,
    )
    assert key == "strategy:9:signal:fp-sell:uba:1380"


def test_live_auto_start_still_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REALTIME_LIVE_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    gate = live_auto_start_allowed(allow_live=True)
    assert gate["allowed"] is False


def test_ma_rebuy_policy_flat_only() -> None:
    """보유 중 추가 BUY 금지 — MA evaluator 정책."""

    from stock_platform.realtime.hub_constants import SignalType
    from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
    from stock_platform.realtime.market_event import RealtimeMarketEvent
    from stock_platform.realtime.strategy_models import (
        RealtimePositionState,
        RealtimeStrategyConfig,
    )
    from stock_platform.strategy_deployment.runtime_scope import (
        AccountKind,
        StrategyRuntimeScope,
    )

    scope = StrategyRuntimeScope(
        user_id=61,
        account_kind=AccountKind.USER_BROKER,
        account_id=1380,
        strategy_id=9,
        strategy_version="1",
        broker_code="UPBIT",
        market_type="CRYPTO",
    )
    evaluator = MovingAverageStrategyEvaluator(
        scope,
        RealtimeStrategyConfig(short_window=2, long_window=3),
    )
    held = RealtimePositionState(
        quantity=Decimal("3.4"),
        average_entry_price=Decimal("1450"),
    )
    now = datetime.now(timezone.utc)
    for i, price in enumerate((100, 101, 102, 103, 104, 200)):
        event = RealtimeMarketEvent(
            broker_code="UPBIT",
            market_type="CRYPTO",
            symbol="KRW-XRP",
            event_type="TICK",
            event_time=now,
            received_at=now,
            exchange_code="UPBIT",
            price=Decimal(str(price)),
            raw_sequence=i + 1,
        )
        signal = evaluator.evaluate(event, position=held)
        if signal is not None and signal.signal_type == SignalType.BUY:
            raise AssertionError("held position must not emit BUY")
