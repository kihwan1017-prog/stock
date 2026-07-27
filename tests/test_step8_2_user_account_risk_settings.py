"""STEP 8-2 — 리스크 설정 우선순위·검증·주문 차단 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskOrderRequest,
    RiskOrderSide,
    RiskPolicy,
)
from stock_platform.risk_engine.engine import RealtimeRiskEngine
from stock_platform.risk_engine.resolved_policy import (
    ResolvedRiskPolicy,
    ResolvedRiskPolicyResolver,
    _row_overlay,
)
from stock_platform.risk_engine.user_risk_service import (
    RiskSettingValidationError,
    validate_risk_payload,
)


def test_validate_rejects_negative_amount() -> None:
    with pytest.raises(RiskSettingValidationError):
        validate_risk_payload({"max_order_amount": -1})


def test_validate_rejects_rate_above_one() -> None:
    with pytest.raises(RiskSettingValidationError):
        validate_risk_payload({"stop_loss_rate": Decimal("1.5")})


def test_validate_stop_vs_take_profit() -> None:
    with pytest.raises(RiskSettingValidationError):
        validate_risk_payload(
            {
                "stop_loss_rate": Decimal("0.10"),
                "take_profit_rate": Decimal("0.05"),
            }
        )


def test_sell_only_forces_buy_disabled() -> None:
    cleaned = validate_risk_payload(
        {"sell_only": True, "buy_enabled": True}
    )
    assert cleaned["buy_enabled"] is False


def test_overlay_partial_account_fields() -> None:
    base = {
        "max_order_amount": Decimal("100000"),
        "stop_loss_rate": Decimal("0.05"),
        "buy_enabled": True,
    }
    account = MagicMock()
    account.max_order_amount = Decimal("50000")
    account.stop_loss_rate = None
    account.buy_enabled = False
    # _OVERLAY_FIELDS 전체를 getattr — 없는 필드는 None
    for name in (
        "daily_max_order_amount",
        "max_total_investment_amount",
        "max_position_amount",
        "max_position_count",
        "max_position_weight",
        "allow_duplicate_buy",
        "daily_max_loss_amount",
        "daily_max_loss_rate",
        "take_profit_rate",
        "trailing_stop_rate",
        "auto_trading_enabled",
        "sell_enabled",
        "sell_only",
        "account_paused",
    ):
        setattr(account, name, None)
    merged = _row_overlay(base, account)
    assert merged["max_order_amount"] == Decimal("50000")
    assert merged["stop_loss_rate"] == Decimal("0.05")
    assert merged["buy_enabled"] is False


def test_priority_system_user_account() -> None:
    session = MagicMock()

    system = MagicMock()
    for f in (
        "max_order_amount",
        "daily_max_order_amount",
        "max_total_investment_amount",
        "max_position_amount",
        "max_position_count",
        "max_position_weight",
        "allow_duplicate_buy",
        "daily_max_loss_amount",
        "daily_max_loss_rate",
        "stop_loss_rate",
        "take_profit_rate",
        "trailing_stop_rate",
        "auto_trading_enabled",
        "buy_enabled",
        "sell_enabled",
        "sell_only",
        "account_paused",
        "max_order_quantity",
        "daily_order_limit",
        "duplicate_order_window_seconds",
    ):
        setattr(system, f, None)
    system.max_order_amount = Decimal("100000")
    system.stop_loss_rate = Decimal("0.05")
    system.take_profit_rate = Decimal("0.10")
    system.daily_max_order_amount = Decimal("1000000")
    system.max_total_investment_amount = Decimal("5000000")
    system.max_position_amount = Decimal("1000000")
    system.max_position_count = 5
    system.max_position_weight = Decimal("0.2")
    system.allow_duplicate_buy = True
    system.daily_max_loss_amount = Decimal("300000")
    system.daily_max_loss_rate = Decimal("0.05")
    system.trailing_stop_rate = Decimal("0.03")
    system.auto_trading_enabled = True
    system.buy_enabled = True
    system.sell_enabled = True
    system.sell_only = False
    system.account_paused = False
    system.max_order_quantity = Decimal("100")
    system.daily_order_limit = 20
    system.duplicate_order_window_seconds = 5

    user = MagicMock()
    for f in (
        "max_order_amount",
        "daily_max_order_amount",
        "max_total_investment_amount",
        "max_position_amount",
        "max_position_count",
        "max_position_weight",
        "allow_duplicate_buy",
        "daily_max_loss_amount",
        "daily_max_loss_rate",
        "stop_loss_rate",
        "take_profit_rate",
        "trailing_stop_rate",
        "auto_trading_enabled",
        "buy_enabled",
        "sell_enabled",
        "sell_only",
        "account_paused",
        "max_order_quantity",
        "daily_order_limit",
        "duplicate_order_window_seconds",
    ):
        setattr(user, f, None)
    user.max_order_amount = Decimal("80000")

    account = MagicMock()
    for f in (
        "max_order_amount",
        "daily_max_order_amount",
        "max_total_investment_amount",
        "max_position_amount",
        "max_position_count",
        "max_position_weight",
        "allow_duplicate_buy",
        "daily_max_loss_amount",
        "daily_max_loss_rate",
        "stop_loss_rate",
        "take_profit_rate",
        "trailing_stop_rate",
        "auto_trading_enabled",
        "buy_enabled",
        "sell_enabled",
        "sell_only",
        "account_paused",
        "max_order_quantity",
        "daily_order_limit",
        "duplicate_order_window_seconds",
    ):
        setattr(account, f, None)
    account.max_order_amount = Decimal("30000")

    # scalar 호출 순서: system, user, account
    session.scalar.side_effect = [system, user, account]
    resolved = ResolvedRiskPolicyResolver(session).resolve(
        user_id=1, user_broker_account_id=9
    )
    assert resolved.max_order_amount == Decimal("30000")
    assert "account" in resolved.source_layers
    assert "user" in resolved.source_layers


def _account() -> RiskAccountState:
    return RiskAccountState(
        cash_balance=Decimal("10000000"),
        total_asset_value=Decimal("10000000"),
        invested_amount=Decimal("0"),
        daily_realized_profit_loss=Decimal("0"),
        daily_unrealized_profit_loss=Decimal("0"),
        open_position_count=0,
        symbol_position_quantity=Decimal("0"),
    )


def _buy(amount: Decimal, *, source: str = "MANUAL") -> RiskOrderRequest:
    qty = Decimal("1")
    return RiskOrderRequest(
        exchange_code="KRX",
        symbol="005930",
        side=RiskOrderSide.BUY,
        quantity=qty,
        price=amount,
        account_id=1,
        requested_at=datetime.now(timezone.utc),
        order_source=source,
    )


def test_engine_blocks_max_order_amount() -> None:
    policy = RiskPolicy(max_order_amount=Decimal("100000"))
    result = RealtimeRiskEngine().evaluate(
        order=_buy(Decimal("200000")),
        account=_account(),
        policy=policy,
    )
    assert result.allowed is False


def test_engine_blocks_sell_only_buy() -> None:
    policy = RiskPolicy(sell_only=True, buy_enabled=True)
    result = RealtimeRiskEngine().evaluate(
        order=_buy(Decimal("1000")),
        account=_account(),
        policy=policy,
    )
    assert result.allowed is False
    assert any(r.rule_code == "SELL_ONLY" for r in result.results)


def test_engine_blocks_auto_when_disabled() -> None:
    policy = RiskPolicy(auto_trading_enabled=False)
    result = RealtimeRiskEngine().evaluate(
        order=_buy(Decimal("1000"), source="AUTO"),
        account=_account(),
        policy=policy,
    )
    assert result.allowed is False


def test_engine_allows_risk_reducing_sell_when_paused() -> None:
    policy = RiskPolicy(
        account_paused=True,
        enforce_krx_market_hours=False,
    )
    order = RiskOrderRequest(
        exchange_code="KRX",
        symbol="005930",
        side=RiskOrderSide.SELL,
        quantity=Decimal("1"),
        price=Decimal("70000"),
        account_id=1,
        requested_at=datetime.now(timezone.utc),
        order_source="EXIT",
        is_risk_reducing=True,
    )
    # 보유 수량 충족
    account = RiskAccountState(
        cash_balance=Decimal("0"),
        total_asset_value=Decimal("70000"),
        invested_amount=Decimal("70000"),
        daily_realized_profit_loss=Decimal("0"),
        daily_unrealized_profit_loss=Decimal("0"),
        open_position_count=1,
        symbol_position_quantity=Decimal("1"),
    )
    result = RealtimeRiskEngine().evaluate(
        order=order, account=account, policy=policy
    )
    assert result.allowed is True


def test_jwt_viewer_role_not_admin_for_flags() -> None:
    user = AuthenticatedUser(
        user_id=1,
        username="u",
        roles=["viewer"],
        permissions=["trading:write"],
    )
    assert user.is_admin is False


def test_resolved_to_engine_policy_maps_limits() -> None:
    resolved = ResolvedRiskPolicy(
        max_order_amount=Decimal("1"),
        daily_max_order_amount=Decimal("2"),
        max_total_investment_amount=Decimal("3"),
        max_position_amount=Decimal("4"),
        max_position_count=2,
        max_position_weight=Decimal("0.1"),
        allow_duplicate_buy=False,
        daily_max_loss_amount=Decimal("5"),
        daily_max_loss_rate=Decimal("0.02"),
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
    policy = resolved.to_engine_policy()
    assert policy.max_order_amount == Decimal("1")
    assert policy.daily_max_order_amount == Decimal("2")
    assert policy.max_open_positions == 2
    assert policy.allow_duplicate_buy is False
    assert policy.max_order_quantity == Decimal("100")
    assert policy.daily_order_limit == 20
