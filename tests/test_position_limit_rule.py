from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskDecisionLevel,
    RiskOrderRequest,
    RiskOrderSide,
)
from stock_platform.risk_engine.position_limit_models import (
    PositionLimitPolicy,
)
from stock_platform.risk_engine.position_limit_rule import (
    DatabasePositionLimitRule,
)


class FakeRepository:
    def get(self, **kwargs):
        return None


def test_blocks_projected_position_amount() -> None:
    rule = DatabasePositionLimitRule.__new__(
        DatabasePositionLimitRule
    )
    rule._repository = FakeRepository()
    rule._broker_code = "KIWOOM"
    rule._account_number = "123"
    rule._default_policy = PositionLimitPolicy(
        max_symbol_quantity=Decimal("100"),
        max_symbol_amount=Decimal("500000"),
        max_symbol_weight=Decimal("0.25"),
    )

    result = rule.evaluate(
        order=RiskOrderRequest(
            exchange_code="KRX",
            symbol="005930",
            side=RiskOrderSide.BUY,
            quantity=Decimal("5"),
            price=Decimal("72000"),
            account_id=1,
            requested_at=datetime.now(timezone.utc),
        ),
        account=RiskAccountState(
            cash_balance=Decimal("1000000"),
            total_asset_value=Decimal("2000000"),
            invested_amount=Decimal("500000"),
            daily_realized_profit_loss=Decimal("0"),
            daily_unrealized_profit_loss=Decimal("0"),
            open_position_count=2,
            symbol_position_quantity=Decimal("3"),
        ),
    )

    assert result.level == RiskDecisionLevel.BLOCK
    assert result.rule_code == "POSITION_LIMIT"


def test_sell_always_reduces_exposure() -> None:
    rule = DatabasePositionLimitRule.__new__(
        DatabasePositionLimitRule
    )
    rule._repository = FakeRepository()
    rule._broker_code = "KIWOOM"
    rule._account_number = "123"
    rule._default_policy = PositionLimitPolicy()

    result = rule.evaluate(
        order=RiskOrderRequest(
            exchange_code="KRX",
            symbol="005930",
            side=RiskOrderSide.SELL,
            quantity=Decimal("1"),
            price=Decimal("72000"),
            account_id=1,
            requested_at=datetime.now(timezone.utc),
        ),
        account=RiskAccountState(
            cash_balance=Decimal("1000000"),
            total_asset_value=Decimal("2000000"),
            invested_amount=Decimal("500000"),
            daily_realized_profit_loss=Decimal("0"),
            daily_unrealized_profit_loss=Decimal("0"),
            open_position_count=2,
            symbol_position_quantity=Decimal("3"),
        ),
    )

    assert result.level == RiskDecisionLevel.PASS
