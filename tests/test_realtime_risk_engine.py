from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.risk_engine.engine import (
    RealtimeRiskEngine,
)
from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskDecisionLevel,
    RiskOrderRequest,
    RiskOrderSide,
    RiskPolicy,
)


def _order(
    *,
    side: RiskOrderSide = RiskOrderSide.BUY,
    quantity: str = "1",
    price: str = "50000",
) -> RiskOrderRequest:
    return RiskOrderRequest(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        account_id=1,
        requested_at=datetime.now(timezone.utc),
    )


def _account() -> RiskAccountState:
    return RiskAccountState(
        cash_balance=Decimal("1000000"),
        total_asset_value=Decimal("2000000"),
        invested_amount=Decimal("500000"),
        daily_realized_profit_loss=Decimal("0"),
        daily_unrealized_profit_loss=Decimal("0"),
        open_position_count=2,
        symbol_position_quantity=Decimal("1"),
    )


def test_passes_safe_buy_order() -> None:
    result = RealtimeRiskEngine().evaluate(
        order=_order(),
        account=_account(),
        policy=RiskPolicy(
            enforce_krx_market_hours=False
        ),
    )

    assert result.allowed is True
    assert result.decision == RiskDecisionLevel.PASS


def test_blocks_order_amount_over_limit() -> None:
    result = RealtimeRiskEngine().evaluate(
        order=_order(
            quantity="3",
            price="50000",
        ),
        account=_account(),
        policy=RiskPolicy(
            max_order_amount=Decimal("100000"),
            enforce_krx_market_hours=False,
        ),
    )

    assert result.allowed is False
    assert result.decision == RiskDecisionLevel.BLOCK
    assert any(
        item.rule_code == "MAX_ORDER_AMOUNT"
        and item.level == RiskDecisionLevel.BLOCK
        for item in result.results
    )


def test_emergency_stop_allows_sell_only() -> None:
    policy = RiskPolicy(
        emergency_stop_enabled=True,
        allow_sell_during_emergency_stop=True,
        enforce_krx_market_hours=False,
    )

    buy_result = RealtimeRiskEngine().evaluate(
        order=_order(side=RiskOrderSide.BUY),
        account=_account(),
        policy=policy,
    )
    sell_result = RealtimeRiskEngine().evaluate(
        order=_order(side=RiskOrderSide.SELL),
        account=_account(),
        policy=policy,
    )

    assert buy_result.allowed is False
    assert sell_result.allowed is True
    assert sell_result.decision == (
        RiskDecisionLevel.WARNING
    )
