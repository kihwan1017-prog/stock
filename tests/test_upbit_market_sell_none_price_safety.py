"""UPBIT MARKET SELL price=None — LiveOrderSafetyPipeline regression.

WRK-20260829-UPBIT-MARKET-SELL-NONE-PRICE-FIX
REAL broker / REAL orders 금지. mock/stub only.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy


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


def _uba_upbit(*, live: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        user_broker_account_id=1380,
        user_id=61,
        broker_code="UPBIT",
        account_alias="upbit-test",
        masked_account_number="***1380",
        is_active=True,
        live_order_enabled=live,
        live_approved_at=None,
        live_approved_by=None,
        live_armed=True,
        arm_token_hash=None,
        arm_expires_at=None,
    )


def _exit_ok(*, held: str = "10", sellable: str | None = None) -> SimpleNamespace:
    sellable_q = Decimal(sellable) if sellable is not None else Decimal(held)
    return SimpleNamespace(
        is_risk_reducing_exit=True,
        reason_code="EXIT_OK",
        held_quantity=Decimal(held),
        pending_sell_quantity=Decimal("0"),
        sellable_quantity=sellable_q,
    )


def _exit_reject(*, held: str = "1", sellable: str = "1") -> SimpleNamespace:
    return SimpleNamespace(
        is_risk_reducing_exit=False,
        reason_code="SELL_QUANTITY_EXCEEDS_SELLABLE",
        held_quantity=Decimal(held),
        pending_sell_quantity=Decimal("0"),
        sellable_quantity=Decimal(sellable),
    )


def _pipeline_session(uba: SimpleNamespace) -> MagicMock:
    session = MagicMock()
    session.get.return_value = uba

    def _scalar(_stmt=None, **_kwargs):  # noqa: ANN001
        # duplicate window 조회는 None, 카운트류는 0
        return None

    session.scalar.side_effect = _scalar
    session.scalars.return_value = []
    return session


def _run_evaluate(**kwargs):
    uba = kwargs.pop("uba", _uba_upbit())
    session = _pipeline_session(uba)
    exit_clf = kwargs.pop("exit_clf", _exit_ok())
    policy = kwargs.pop("policy", _policy())
    defaults = dict(
        user_id=61,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        exchange_code="UPBIT",
        symbol="KRW-XRP",
        emit_side_effects=False,
        require_arm=False,
        skip_market_hours=True,
    )
    defaults.update(kwargs)
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=exit_clf,
        ),
        patch(
            "stock_platform.order.live_safety_pipeline.evaluate_live_open_order_exposure",
            return_value=SimpleNamespace(
                auto_open_count=0,
                manual_open_count=0,
                unknown_open_count=0,
                total_open_count=0,
                remote_state_ok=True,
                remote_state="OK",
                reason_code=None,
                as_detail=lambda: {
                    "auto_open_orders": 0,
                    "manual_open_orders": 0,
                    "unknown_open_orders": 0,
                    "remote_open_state": "OK",
                },
            ),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="LIVE_SAFE_DEFAULTS"),
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = policy
        return LiveOrderSafetyPipeline(session).evaluate(**defaults)


def test_market_sell_none_price_does_not_raise_and_can_pass() -> None:
    """price=None + valid qty → Decimal(None) 없이 pass 가능."""
    decision = _run_evaluate(
        side="SELL",
        order_type="MARKET",
        quantity=Decimal("2.5"),
        price=None,
        reference_price=Decimal("1900"),
    )
    assert decision.allowed is True
    assert decision.reason_code == "LIVE_SAFETY_PASS"
    assert decision.detail.get("amount_basis") == "MARKET_SELL_REFERENCE_ESTIMATE"


def test_market_sell_none_price_without_reference_still_passes_qty_gates() -> None:
    """reference 없어도 0 위장 없이 qty 기반 pass (amount=None)."""
    decision = _run_evaluate(
        side="SELL",
        order_type="MARKET",
        quantity=Decimal("2.5"),
        price=None,
        reference_price=None,
    )
    assert decision.allowed is True
    assert decision.detail.get("amount") is None
    assert decision.detail.get("amount_basis") == "NONE"


def test_market_sell_invalid_quantity_domain_reject() -> None:
    decision = _run_evaluate(
        side="SELL",
        order_type="MARKET",
        quantity=Decimal("0"),
        price=None,
    )
    assert decision.allowed is False
    assert decision.reason_code == "INVALID_ORDER_QUANTITY"


def test_limit_sell_missing_price_rejected() -> None:
    decision = _run_evaluate(
        side="SELL",
        order_type="LIMIT",
        quantity=Decimal("2.5"),
        price=None,
    )
    assert decision.allowed is False
    assert decision.reason_code == "LIMIT_PRICE_REQUIRED"


def test_limit_sell_valid_price_passes() -> None:
    decision = _run_evaluate(
        side="SELL",
        order_type="LIMIT",
        quantity=Decimal("3"),
        price=Decimal("1910"),  # notional >= 5000
    )
    assert decision.allowed is True
    assert decision.reason_code == "LIVE_SAFETY_PASS"
    assert decision.detail.get("amount_basis") == "LIMIT_PRICE"


def test_market_buy_quote_unchanged() -> None:
    decision = _run_evaluate(
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("1"),
        price=Decimal("5500"),  # KRW notional from resolve_size
        order_amount=Decimal("5500"),
    )
    assert decision.allowed is True
    assert decision.detail.get("amount_basis") == "MARKET_BUY_QUOTE"
    assert Decimal(decision.detail["amount"]) == Decimal("5500.00")


def test_limit_buy_unchanged() -> None:
    decision = _run_evaluate(
        side="BUY",
        order_type="LIMIT",
        quantity=Decimal("3"),
        price=Decimal("1900"),  # notional >= 5000
    )
    assert decision.allowed is True
    assert decision.detail.get("amount_basis") == "LIMIT_PRICE"


def test_market_sell_exceeds_sellable_balance_rejected() -> None:
    decision = _run_evaluate(
        side="SELL",
        order_type="MARKET",
        quantity=Decimal("100"),
        price=None,
        exit_clf=_exit_reject(held="2", sellable="2"),
    )
    assert decision.allowed is False
    assert decision.reason_code in {
        "SELL_QUANTITY_EXCEEDS_SELLABLE",
        "NO_POSITION_TO_SELL",
    }


def test_live_off_still_blocks_market_sell() -> None:
    decision = _run_evaluate(
        uba=_uba_upbit(live=False),
        side="SELL",
        order_type="MARKET",
        quantity=Decimal("1"),
        price=None,
    )
    assert decision.allowed is False
    assert decision.reason_code == "LIVE_ORDER_DISABLED"


def test_kill_switch_still_blocks_market_sell() -> None:
    uba = _uba_upbit()
    session = _pipeline_session(uba)
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=_exit_ok(),
        ),
    ):
        resolver_cls.return_value.resolve.return_value = _policy()
        ks.return_value.require_order_allowed.side_effect = PermissionError(
            "KILL"
        )
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=61,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol="KRW-XRP",
            side="SELL",
            order_type="MARKET",
            quantity=Decimal("1"),
            price=None,
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert decision.allowed is False
    assert decision.reason_code == "KILL_SWITCH_ACTIVE"


def test_resolve_size_market_sell_returns_none_price() -> None:
    """execution_service: UPBIT MARKET SELL → broker price=None (정상)."""
    session = MagicMock()
    svc = OrderExecutionService(session)
    qty, price, meta = svc._resolve_size(
        OrderExecutionCommand(
            account_id=1,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol="KRW-XRP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("2.86757038"),
            price=Decimal("1918"),  # reference only
            environment="LIVE",
            user_broker_account_id=1380,
        )
    )
    assert qty == Decimal("2.86757038")
    assert price is None
    assert meta is not None
    assert meta.get("broker_price_semantics") == "UPBIT_MARKET_SELL_VOLUME_ONLY"
    assert meta.get("reference_price") == "1918"


def test_decimal_str_none_no_longer_occurs_on_evaluate() -> None:
    """직접 Decimal(str(None)) 경로가 evaluate에서 재발하지 않음."""
    with pytest.raises(Exception):
        Decimal(str(None))
    # evaluate는 예외 없이 domain decision 반환
    decision = _run_evaluate(
        side="SELL",
        order_type="MARKET",
        quantity=Decimal("1"),
        price=None,
    )
    assert decision.reason_code in {"LIVE_SAFETY_PASS", "LIVE_ORDER_DISABLED"}
    assert decision.allowed is True
