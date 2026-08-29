"""STEP 8-8 — LIVE 운영 보호 (ARM·슬리피지·한도·검증) 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline
from stock_platform.order.post_fill_verifier import PostFillBalanceVerifier
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy
from stock_platform.trading.broker_disconnect_protector import (
    BrokerDisconnectProtector,
)
from stock_platform.trading.live_arm_service import LiveArmService


def _policy(**overrides) -> ResolvedRiskPolicy:
    base = dict(
        max_order_amount=Decimal("50000"),
        daily_max_order_amount=Decimal("200000"),
        max_total_investment_amount=Decimal("1000000"),
        max_position_amount=Decimal("200000"),
        max_position_count=5,
        max_position_weight=Decimal("0.2"),
        max_investment_ratio=Decimal("0.70"),
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


def _uba(*, live=True, armed=False, token_hash=None, expires=None):
    return SimpleNamespace(
        user_broker_account_id=10,
        user_id=1,
        broker_code="KIWOOM",
        is_active=True,
        live_order_enabled=live,
        live_armed=armed,
        arm_token_hash=token_hash,
        arm_expires_at=expires,
        arm_armed_by="admin",
        arm_armed_at=datetime.now(timezone.utc),
        live_approved_at=None,
        live_approved_by=None,
    )


def test_arm_requires_live_on() -> None:
    session = MagicMock()
    uba = _uba(live=False)
    session.get.return_value = uba
    with patch(
        "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
    ) as R:
        R.return_value.resolve.return_value = _policy()
        try:
            LiveArmService(session).arm(10, actor="admin")
            raised = False
        except Exception as exc:
            raised = "LIVE_ORDER_DISABLED" in str(exc)
    assert raised is True


def test_arm_issues_token_and_validates() -> None:
    session = MagicMock()
    uba = _uba(live=True)
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
        ) as R,
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
        patch.object(
            LiveArmService,
            "_require_session_activation",
            return_value=SimpleNamespace(
                live_trading_transition_id=1,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
                broker_code="KIWOOM",
                user_broker_account_id=10,
            ),
        ),
    ):
        R.return_value.resolve.return_value = _policy()
        result = LiveArmService(session).arm(10, actor="admin", ttl_seconds=300)
    assert result["live_armed"] is True
    assert "arm_token" in result
    token = result["arm_token"]
    ok, reason = LiveArmService(session).validate_arm_token(10, token)
    assert ok is True
    assert reason == "ARM_OK"


def test_arm_token_mismatch_rejects() -> None:
    session = MagicMock()
    token = "good-token"
    uba = _uba(
        live=True,
        armed=True,
        token_hash=LiveArmService.hash_token(token),
        expires=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    session.get.return_value = uba
    ok, reason = LiveArmService(session).validate_arm_token(10, "bad-token")
    assert ok is False
    assert reason == "ARM_TOKEN_MISMATCH"


def test_arm_expired_turns_live_off() -> None:
    session = MagicMock()
    uba = _uba(
        live=True,
        armed=True,
        token_hash="abc",
        expires=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
    ):
        ok, reason = LiveArmService(session).validate_arm_token(10, "x")
    assert ok is False
    assert reason == "LIVE_ARM_EXPIRED"
    assert uba.live_order_enabled is False
    assert uba.live_armed is False


def test_pipeline_rejects_without_arm() -> None:
    session = MagicMock()
    uba = _uba(live=True, armed=False)
    session.get.return_value = uba
    with patch(
        "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
    ) as R:
        R.return_value.resolve.return_value = _policy()
        d = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            emit_side_effects=False,
            require_arm=True,
            arm_token=None,
            skip_market_hours=True,
        )
    assert d.allowed is False
    assert d.reason_code in {"LIVE_NOT_ARMED", "ARM_TOKEN_MISSING"}


def test_slippage_rejects_buy_above_limit() -> None:
    session = MagicMock()
    uba = _uba(live=True)
    session.get.return_value = uba
    session.scalar.side_effect = [0, 0, 0, None, None]  # daily, open, 1m, dup, loss
    # Actually order: after ARM skip path with require_arm=False:
    # daily, loss, dup, open, 1m, loop uses scalars differently
    session.scalar.side_effect = [
        0,  # daily
        None,  # loss
        None,  # dup
        0,  # open
        0,  # per min
        # loop uses scalars list of rows via scalars() not scalar
    ]
    session.scalars.return_value = []
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as R,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as KS,
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency"
        ) as F,
    ):
        KS.return_value.require_order_allowed.return_value = None
        R.return_value.resolve.return_value = _policy(
            max_slippage_rate=Decimal("0.01")
        )
        F.return_value = SimpleNamespace(code="LIVE_SAFE_DEFAULTS")
        d = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("10350"),
            reference_price=Decimal("10000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert d.allowed is False
    assert d.reason_code == "SLIPPAGE_EXCEEDED"


def test_open_order_limit_rejects() -> None:
    session = MagicMock()
    uba = _uba(live=True)
    session.get.return_value = uba
    # daily, loss, dup, open=20
    session.scalar.side_effect = [0, None, None, 20]
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as R,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as KS,
    ):
        KS.return_value.require_order_allowed.return_value = None
        R.return_value.resolve.return_value = _policy(max_open_orders=20)
        d = LiveOrderSafetyPipeline(session).evaluate(
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
    assert d.allowed is False
    assert d.reason_code == "OPEN_ORDER_LIMIT_EXCEEDED"


def test_position_mismatch_activates_kill() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
        ) as KS,
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService"
        ) as ARM,
        patch(
            "stock_platform.order.post_fill_verifier.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.order.post_fill_verifier.emit_live_order_telegram"
        ),
    ):
        KS.return_value.activate.return_value = None
        ARM.return_value.disarm.return_value = {}
        result = PostFillBalanceVerifier(session).verify(
            user_broker_account_id=10,
            user_id=1,
            broker_code="KIWOOM",
            broker_positions=[{"symbol": "005930", "quantity": "10"}],
            broker_cash=None,
            db_positions=[{"symbol": "005930", "quantity": "9"}],
            db_cash=None,
        )
    assert result.ok is False
    assert result.reason_code == "POSITION_MISMATCH"
    KS.return_value.activate.assert_called_once()


def test_broker_disconnect_turns_live_off() -> None:
    session = MagicMock()
    uba = _uba(live=True, armed=True)
    session.scalars.return_value = [uba]
    with (
        patch(
            "stock_platform.trading.broker_disconnect_protector.LiveArmService"
        ) as ARM,
        patch(
            "stock_platform.trading.broker_disconnect_protector.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.broker_disconnect_protector.emit_live_order_telegram"
        ),
    ):
        ARM.return_value.disarm.return_value = {}
        out = BrokerDisconnectProtector(session).on_broker_down(
            broker_code="KIWOOM", actor="test"
        )
        recovered = BrokerDisconnectProtector(session).on_broker_up(
            broker_code="KIWOOM"
        )
    assert 10 in out["disabled_accounts"]
    assert recovered["auto_live_on"] is False
    assert recovered["requires_admin_arm"] is True


def test_pipeline_pass_with_arm_bypassed_and_limits() -> None:
    session = MagicMock()
    uba = _uba(live=True)
    session.get.return_value = uba
    session.scalar.side_effect = [0, None, None, 0, 0]
    session.scalars.return_value = []
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as R,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as KS,
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency"
        ) as F,
    ):
        KS.return_value.require_order_allowed.return_value = None
        R.return_value.resolve.return_value = _policy()
        F.return_value = SimpleNamespace(code="LIVE_SAFE_DEFAULTS")
        d = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            reference_price=Decimal("1000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert d.allowed is True
