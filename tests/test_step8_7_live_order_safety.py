"""STEP 8-7 ??LIVE 주문 ?�전 게이???�스??"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.order.live_safety_pipeline import (
    LiveOrderSafetyPipeline,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy
from stock_platform.trading.live_order_approval_service import (
    LiveOrderApprovalService,
)


def _policy(**overrides) -> ResolvedRiskPolicy:
    base = dict(
        max_order_amount=Decimal("50000"),
        daily_max_order_amount=Decimal("200000"),
        max_total_investment_amount=Decimal("1000000"),
        max_position_amount=Decimal("200000"),
        max_position_count=5,
        max_position_weight=Decimal("0.2"),
        allow_duplicate_buy=True,
        daily_max_loss_amount=Decimal("30000"),
        daily_max_loss_rate=Decimal("0.05"),
        stop_loss_rate=Decimal("0.05"),
        take_profit_rate=Decimal("0.1"),
        trailing_stop_rate=Decimal("0.03"),
        auto_trading_enabled=True,
        buy_enabled=True,
        sell_enabled=True,
        sell_only=False,
        account_paused=False,
        max_order_quantity=Decimal("100"),
        daily_order_limit=20,
        duplicate_order_window_seconds=5,
        max_open_orders=20,
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("system",),
    )
    base.update(overrides)
    return ResolvedRiskPolicy(**base)


def _uba(*, live: bool = False, user_id: int = 1, active: bool = True, armed: bool = False):
    return SimpleNamespace(
        user_broker_account_id=10,
        user_id=user_id,
        broker_code="KIWOOM",
        account_alias="test",
        masked_account_number="***1234",
        is_active=active,
        live_order_enabled=live,
        live_approved_at=None,
        live_approved_by=None,
        live_armed=armed,
        arm_token_hash=None,
        arm_expires_at=None,
    )


def _pipeline_session(uba, *, policy=None, daily_count=0, duplicate=None):
    session = MagicMock()
    session.get.return_value = uba
    # scalar 호출 순서: daily → loss → dup → open → per_min
    session.scalar.side_effect = [
        daily_count,
        None,
        duplicate,
        0,
        0,
    ]
    session.scalars.return_value = []
    return session


def test_live_off_rejects_order() -> None:
    uba = _uba(live=False)
    session = _pipeline_session(uba)
    with patch(
        "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
    ) as resolver_cls:
        resolver_cls.return_value.resolve.return_value = _policy()
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            emit_side_effects=False,
        require_arm=False,
        )
    assert decision.allowed is False
    assert decision.reason_code == "LIVE_ORDER_DISABLED"
    assert decision.audit_event_type == "LIVE_REJECTED"


def test_amount_exceeded_rejects() -> None:
    uba = _uba(live=True)
    session = _pipeline_session(uba)
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = _policy(
            max_order_amount=Decimal("50000")
        )
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("100"),
            price=Decimal("1000"),  # 100_000 > 50_000
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert decision.allowed is False
    assert decision.reason_code == "ORDER_AMOUNT_EXCEEDED"
    assert decision.audit_event_type == "ORDER_AMOUNT_REJECT"


def test_qty_exceeded_rejects() -> None:
    uba = _uba(live=True)
    session = _pipeline_session(uba)
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = _policy(
            max_order_quantity=Decimal("10")
        )
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("11"),
            price=Decimal("1000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert decision.allowed is False
    assert decision.reason_code == "ORDER_QTY_EXCEEDED"


def test_daily_limit_rejects() -> None:
    uba = _uba(live=True)
    session = _pipeline_session(uba, daily_count=20)
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = _policy(
            daily_order_limit=20
        )
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert decision.allowed is False
    assert decision.reason_code == "DAILY_ORDER_LIMIT_EXCEEDED"


def test_duplicate_rejects() -> None:
    uba = _uba(live=True)
    dup = SimpleNamespace(order_id=99)
    session = MagicMock()
    session.get.return_value = uba
    # scalar: daily_count → daily_loss → duplicate
    session.scalar.side_effect = [0, None, dup]
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = _policy()
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert decision.allowed is False
    assert decision.reason_code == "DUPLICATE_ORDER"


def test_kill_switch_rejects() -> None:
    uba = _uba(live=True)
    session = _pipeline_session(uba)
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
    ):
        ks.return_value.require_order_allowed.side_effect = PermissionError(
            "KILL"
        )
        resolver_cls.return_value.resolve.return_value = _policy()
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert decision.allowed is False
    assert decision.reason_code == "KILL_SWITCH_ACTIVE"


def test_market_closed_rejects() -> None:
    uba = _uba(live=True)
    session = _pipeline_session(uba)
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.operation.calendar_service.TradingCalendarService"
        ) as cal,
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = _policy()
        cal.return_value.require_live_order_session.side_effect = ValueError(
            "KRX market closed: HOLIDAY"
        )
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=False,
        )
    assert decision.allowed is False
    assert decision.reason_code == "MARKET_CLOSED"


def test_broker_health_rejects() -> None:
    uba = _uba(live=True)
    session = _pipeline_session(uba)
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ) as health,
    ):
        from stock_platform.operation.live_health_gate import (
            LiveHealthBlockedError,
        )

        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = _policy()
        health.side_effect = LiveHealthBlockedError("DOWN")
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert decision.allowed is False
    assert decision.reason_code == "BROKER_HEALTH_BLOCKED"


def test_all_conditions_pass_mock() -> None:
    uba = _uba(live=True)
    session = MagicMock()
    session.get.return_value = uba
    # count → loss → duplicate → open → per_min
    session.scalar.side_effect = [0, None, None, 0, 0]
    session.scalars.return_value = []
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency"
        ) as flags,
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = _policy()
        flags.return_value = SimpleNamespace(code="LIVE_SAFE_DEFAULTS")
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert decision.allowed is True
    assert decision.reason_code == "LIVE_SAFETY_PASS"


def test_paper_environment_bypasses_pipeline() -> None:
    session = MagicMock()
    decision = LiveOrderSafetyPipeline(session).evaluate(
        user_id=1,
        user_broker_account_id=10,
        broker_code="PAPER",
        exchange_code="KRX",
        symbol="005930",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("1000"),
        environment="PAPER",
        emit_side_effects=False,
    require_arm=False,
    )
    assert decision.allowed is True
    assert decision.reason_code == "NOT_LIVE"


def test_execution_service_live_off_blocked() -> None:
    session = MagicMock()
    service = OrderExecutionService(session)
    with (
        patch.object(
            service,
            "_resolve_size",
            return_value=(Decimal("1"), Decimal("1000"), None),
        ),
        patch(
            "stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline"
        ) as pipe,
    ):
        pipe.return_value.evaluate.return_value = SimpleNamespace(
            allowed=False,
            reason_code="LIVE_ORDER_DISABLED",
        )
        result = service.submit(
            OrderExecutionCommand(
                account_id=1,
                broker_code="KIWOOM",
                exchange_code="KRX",
                symbol="005930",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("1000"),
                quantity=Decimal("1"),
                environment="LIVE",
                user_broker_account_id=10,
                user_id=1,
                external_account_ref="UBA:10",
            )
        )
    assert result.allowed is False
    assert result.reason_code == "LIVE_ORDER_DISABLED"


def test_approval_service_defaults_off() -> None:
    session = MagicMock()
    uba = _uba(live=False)
    session.get.return_value = uba
    with patch(
        "stock_platform.trading.live_order_approval_service.ResolvedRiskPolicyResolver"
    ) as resolver:
        resolver.return_value.resolve.return_value = _policy()
        status = LiveOrderApprovalService(session).get_status(10)
    assert status["live_order_enabled"] is False


def test_approval_service_enable_sets_flag() -> None:
    session = MagicMock()
    uba = _uba(live=False)
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.live_order_approval_service.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.trading.live_order_approval_service.emit_live_safety_audit"
        ),
    ):
        resolver.return_value.resolve.return_value = _policy()
        LiveOrderApprovalService(session).set_live_enabled(
            10,
            enabled=True,
            actor="admin",
            reason="TEST_ENABLE",
            correlation_id="test-corr-1",
            enforce_enable_gates=False,
        )
    assert uba.live_order_enabled is True
    assert uba.live_approved_by == "admin"
    assert uba.live_approved_at is not None
    assert uba.live_armed is False


def test_loss_limit_rejects_when_breached() -> None:
    uba = _uba(live=True)
    session = MagicMock()
    session.get.return_value = uba
    loss_row = SimpleNamespace(
        status_code="SAFE",
        current_loss_amount=Decimal("30000"),
    )
    # count ??loss (duplicate 미호�?
    session.scalar.side_effect = [0, loss_row]
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = _policy(
            daily_max_loss_amount=Decimal("30000")
        )
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert decision.allowed is False
    assert decision.reason_code == "DAILY_LOSS_LIMIT_REACHED"
