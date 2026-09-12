"""UPBIT Autotrading Master Gate / 24/7 / Worker — mock tests (실주문 0)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.live_outbox_worker_runtime import (
    LiveOutboxWorkerRuntime,
)
from stock_platform.realtime.autotrading_idempotency import (
    build_autotrading_idempotency_key,
)
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.live_runtime_control import (
    should_keep_upbit_on_krx_close,
    upbit_market_hours_policy,
)
from stock_platform.realtime.risk_integrated_order_executor import (
    RiskIntegratedRealtimeOrderExecutor,
)
from stock_platform.realtime.safety_guard import RealtimeOrderSafetyGuard
from stock_platform.realtime.safety_models import RealtimeOrderSafetyConfig
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)
from stock_platform.trading.autotrading_master_gate import (
    STATUS_BLOCKED,
    STATUS_STRATEGY_REQUIRED,
    admin_set_uba_strategy_link_active,
    evaluate_uba_autotrading_ready,
)


def _uba(**kwargs):
    base = dict(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        is_active=True,
        deleted_at=None,
        live_order_enabled=False,
        live_armed=False,
        live_approved_at=None,
        user_id=61,
        arm_expires_at=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


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
        fingerprint="fp-shadow-e2e",
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


def test_strategy_required_when_no_links() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    session.scalars.return_value = []
    session.scalar.return_value = 0

    with (
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as act,
        patch(
            "stock_platform.trading.upbit_live_pipeline_readiness.UpbitLivePipelineReadinessService"
        ) as pipe,
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime"
        ) as worker,
    ):
        act.return_value.require_active.side_effect = PermissionError("NO")
        pipe.return_value.evaluate.return_value = {
            "ops_ready": False,
            "blockers": [],
            "warnings": [],
            "checks": {},
        }
        worker.status.return_value = {"enabled": False, "running": False}
        out = evaluate_uba_autotrading_ready(
            session, user_broker_account_id=1380
        )
    assert out["status"] == STATUS_STRATEGY_REQUIRED
    assert "STRATEGY_REQUIRED" in out["blockers"]
    assert out["start_button_enabled"] is False
    assert out["checks"]["market_hours"]["applies_krx_session"] is False
    assert out["checks"]["single_uba_config"]["limitation"] == (
        "SINGLE_UBA_SUPPORTED_WITH_LIMITATION"
    )


def test_inactive_link_blocks() -> None:
    session = MagicMock()
    uba = _uba(live_order_enabled=True, live_armed=True)
    link = SimpleNamespace(
        account_strategy_link_id=1,
        strategy_id=9,
        is_active=False,
        user_id=61,
    )
    strategy = SimpleNamespace(
        strategy_id=9,
        is_active=True,
        approved_at=datetime.now(timezone.utc),
        owner_type="USER",
        market_type="CRYPTO",
        strategy_code="MA",
        name="MA",
    )

    def _get(model, pk):
        name = getattr(model, "__name__", str(model))
        if "UserBroker" in name:
            return uba
        if "StrategyDefinition" in name:
            return strategy
        return None

    session.get.side_effect = _get
    session.scalars.return_value = [link]
    session.scalar.return_value = 0
    with (
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as act,
        patch(
            "stock_platform.trading.upbit_live_pipeline_readiness.UpbitLivePipelineReadinessService"
        ) as pipe,
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime"
        ) as worker,
        patch(
            "stock_platform.risk_engine.user_risk_service.UserRiskSettingService"
        ) as risk,
    ):
        act.return_value.require_active.return_value = None
        pipe.return_value.evaluate.return_value = {
            "ops_ready": True,
            "blockers": [],
            "warnings": [],
            "checks": {
                "credential": {"ok": True},
                "quote_ws": {"ok": True},
                "hub_status": {"ok": True},
            },
        }
        worker.status.return_value = {"enabled": True, "running": True}
        risk.return_value.resolve.return_value = SimpleNamespace(
            daily_order_limit=10, max_order_amount=Decimal("5100")
        )
        out = evaluate_uba_autotrading_ready(
            session, user_broker_account_id=1380
        )
    assert out["status"] == STATUS_BLOCKED
    assert "STRATEGY_LINK_INACTIVE" in out["blockers"]


def test_link_activate_requires_public_catalog_approval() -> None:
    session = MagicMock()
    uba = _uba(live_approved_at=datetime.now(timezone.utc))
    strategy = SimpleNamespace(
        is_active=True,
        approved_at=None,
        owner_type="USER",
        visibility="PUBLIC",
        market_type="CRYPTO",
        deleted_at=None,
    )
    session.get.side_effect = lambda model, pk: (
        uba
        if "UserBroker" in getattr(model, "__name__", "")
        else strategy
    )
    session.scalar.return_value = None
    with pytest.raises(ValueError, match="STRATEGY_NOT_APPROVED"):
        admin_set_uba_strategy_link_active(
            session,
            user_broker_account_id=1380,
            strategy_id=9,
            is_active=True,
            actor="admin",
        )


def test_link_activate_private_without_evidence_is_blocked() -> None:
    session = MagicMock()
    uba = _uba(live_approved_at=datetime.now(timezone.utc))
    strategy = SimpleNamespace(
        strategy_id=17580,
        is_active=True,
        approved_at=None,
        owner_type="USER",
        visibility="PRIVATE",
        market_type="CRYPTO",
        deleted_at=None,
        source_strategy_id=17483,
    )
    session.get.side_effect = lambda model, pk: (
        uba
        if "UserBroker" in getattr(model, "__name__", "")
        else strategy
    )
    session.scalar.return_value = None
    session.scalars.return_value = []
    with pytest.raises(ValueError, match="STRATEGY_EVIDENCE_NOT_READY"):
        admin_set_uba_strategy_link_active(
            session,
            user_broker_account_id=1380,
            strategy_id=17580,
            is_active=True,
            actor="admin",
        )


def test_link_activate_requires_live_approval() -> None:
    session = MagicMock()
    uba = _uba(live_approved_at=None)
    strategy = SimpleNamespace(
        is_active=True,
        approved_at=datetime.now(timezone.utc),
        owner_type="USER",
        visibility="PRIVATE",
        market_type="CRYPTO",
        deleted_at=None,
    )
    session.get.side_effect = lambda model, pk: (
        uba
        if "UserBroker" in getattr(model, "__name__", "")
        else strategy
    )
    session.scalar.return_value = None
    with pytest.raises(ValueError, match="LIVE_NOT_APPROVED"):
        admin_set_uba_strategy_link_active(
            session,
            user_broker_account_id=1380,
            strategy_id=9,
            is_active=True,
            actor="admin",
        )


def test_worker_disabled_by_default_startup_fail_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_OUTBOX_WORKER_ENABLED", "false")
    monkeypatch.setenv("LIVE_OUTBOX_WORKER_AUTO_START", "false")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    runtime = LiveOutboxWorkerRuntime()
    st = runtime.status()
    assert st["enabled"] is False
    assert st.get("auto_start") is False
    started = runtime.start()
    assert started["started"] is False
    assert started["reason"] == "LIVE_OUTBOX_WORKER_DISABLED"


def test_market_feed_unhealthy_is_auto_live_blocker() -> None:
    """AUTO LIVE readiness에서 feed unhealthy는 WARN이 아니라 BLOCKER."""

    from stock_platform.trading.autotrading_master_gate import (
        _evaluate_market_feed_for_auto_live,
    )

    out = _evaluate_market_feed_for_auto_live(
        quote_ws={"connected": False, "running": False},
        hub={"dispatch_running": False},
        strategy_symbols=["KRW-XRP"],
    )
    assert out["ok"] is False
    assert out["policy"] == "BLOCK_IF_UNHEALTHY_FOR_AUTO_LIVE"
    assert out["reason"] == "QUOTE_WS_NOT_CONNECTED"


def test_upbit_not_blocked_by_krx_market_hours() -> None:
    guard = RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            live_trading_enabled=True,
            live_unlock_token="T",
            enforce_market_hours_for_krx=True,
            duplicate_order_window_seconds=0,
            symbol_cooldown_seconds=0,
            max_orders_per_minute=100,
        )
    )
    decision = guard.evaluate(
        signal=_signal(),
        mode=RealtimeExecutionMode.LIVE,
        order_amount=Decimal("5000"),
        open_position_count=0,
        live_unlock_token="T",
    )
    assert decision.reason_code != "OUTSIDE_MARKET_HOURS"
    assert decision.allowed is True


def test_krx_still_enforces_market_hours() -> None:
    """KRX 회귀 — enforce 시 세션 Timeline 경로 진입."""

    guard = RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            live_trading_enabled=True,
            live_unlock_token="T",
            enforce_market_hours_for_krx=True,
        )
    )
    signal = _signal(
        exchange_code="KRX", symbol="005930", broker_code="KIWOOM"
    )
    with patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        side_effect=RuntimeError("calendar unavailable"),
    ):
        decision = guard.evaluate(
            signal=signal,
            mode=RealtimeExecutionMode.LIVE,
            order_amount=Decimal("5000"),
            open_position_count=0,
            live_unlock_token="T",
        )
    assert decision.allowed is False


def test_upbit_24x7_policy_default_off() -> None:
    policy = upbit_market_hours_policy()
    assert policy["applies_krx_session"] is False
    assert should_keep_upbit_on_krx_close() is False


def test_master_gate_blockers_live_arm_worker_kill_risk() -> None:
    session = MagicMock()
    uba = _uba(
        live_order_enabled=False,
        live_armed=False,
        live_approved_at=datetime.now(timezone.utc),
        arm_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    link = SimpleNamespace(
        account_strategy_link_id=1,
        strategy_id=9,
        is_active=True,
        user_id=61,
    )
    strategy = SimpleNamespace(
        strategy_id=9,
        is_active=True,
        approved_at=datetime.now(timezone.utc),
        owner_type="USER",
        market_type="CRYPTO",
        strategy_code="MA",
        name="MA",
    )

    def _get(model, pk):
        name = getattr(model, "__name__", str(model))
        if "UserBroker" in name:
            return uba
        if "StrategyDefinition" in name:
            return strategy
        return None

    session.get.side_effect = _get
    session.scalars.return_value = [link]
    session.scalar.return_value = 0
    with (
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as act,
        patch(
            "stock_platform.trading.upbit_live_pipeline_readiness.UpbitLivePipelineReadinessService"
        ) as pipe,
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime"
        ) as worker,
        patch(
            "stock_platform.risk_engine.user_risk_service.UserRiskSettingService"
        ) as risk,
        patch(
            "stock_platform.strategy_deployment.runtime_manager.dynamic_strategy_runtime_manager"
        ) as runtime_mgr,
    ):
        act.return_value.require_active.side_effect = PermissionError(
            "expired"
        )
        pipe.return_value.evaluate.return_value = {
            "ops_ready": False,
            "blockers": ["KILL_SWITCH_ACTIVE"],
            "warnings": [],
            "checks": {
                "quote_ws": {"ok": False},
                "hub_status": {"ok": False},
                "kill": {"active": True},
            },
        }
        worker.status.return_value = {"enabled": False, "running": False}
        risk.return_value.resolve.return_value = None
        runtime_mgr.status.return_value = {"entries": []}
        out = evaluate_uba_autotrading_ready(
            session, user_broker_account_id=1380
        )
    assert out["status"] == STATUS_BLOCKED
    for code in (
        "ACTIVATION_INACTIVE",
        "LIVE_OFF",
        "ARM_OFF_OR_EXPIRED",
        "LIVE_OUTBOX_WORKER_DISABLED",
        "KILL_SWITCH_ACTIVE",
        "RISK_POLICY_MISSING",
        "MARKET_FEED_UNHEALTHY",
    ):
        assert code in out["blockers"]
    assert "MARKET_FEED_UNHEALTHY" not in out["warnings"]
    # active approved link → Runtime READY (RUN 아님)
    assert out["runtime_status"] == "READY"


def test_shadow_e2e_signal_to_outbox_no_adapter_post() -> None:
    """Shadow 경로 Signal→OES 1건 — create_order 실호출 0."""

    session = MagicMock()
    session.scalar.return_value = 0
    guard = RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            live_trading_enabled=True,
            live_unlock_token="UNLOCK",
            max_open_positions=5,
            duplicate_order_window_seconds=0,
            symbol_cooldown_seconds=0,
            max_orders_per_minute=100,
            enforce_market_hours_for_krx=True,
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
            executor, "_resolve_account_number", return_value="uba-1380"
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
            return_value=True,
        ),
        patch(
            "stock_platform.broker.upbit.order_client.UpbitOrderRestClient.create_order"
        ) as create_order,
    ):
        kill_cls.return_value.require_order_allowed.return_value = None
        lock_cls.return_value.is_trading_paused.return_value = False
        risk_cls.return_value.check.return_value = SimpleNamespace(
            allowed=True, blocked_reason=None
        )
        oes_cls.return_value.submit.return_value = submit_result
        first = executor.execute(_signal())
        key_a = build_autotrading_idempotency_key(
            _signal(), user_broker_account_id=1380
        )
        key_b = build_autotrading_idempotency_key(
            _signal(
                generated_at=datetime(
                    2026, 8, 8, 9, 0, tzinfo=timezone.utc
                )
            ),
            user_broker_account_id=1380,
        )

    assert first.order_id == 9001
    assert oes_cls.return_value.submit.call_count == 1
    cmd = oes_cls.return_value.submit.call_args.args[0]
    assert cmd.idempotency_key == key_a == key_b
    assert cmd.user_broker_account_id == 1380
    assert cmd.environment == "LIVE"
    assert create_order.call_count == 0
