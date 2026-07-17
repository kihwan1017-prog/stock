from decimal import Decimal

from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import (
    ExitEvaluationRequest,
    PositionSizingMode,
    PositionSizingRequest,
    RiskPolicy,
)


def test_risk_based_position_plan() -> None:
    engine = RiskManagementEngine()
    policy = RiskPolicy(
        position_sizing_mode=PositionSizingMode.RISK_BASED,
        risk_per_trade_ratio=Decimal("0.01"),
        stop_loss_ratio=Decimal("0.05"),
        take_profit_ratio=Decimal("0.10"),
        maximum_position_ratio=Decimal("0.20"),
        maximum_positions=5,
        minimum_order_amount=Decimal("10000"),
    )

    plan = engine.create_position_plan(
        PositionSizingRequest(
            portfolio_value=Decimal("10000000"),
            available_cash=Decimal("5000000"),
            current_price=Decimal("100000"),
            current_position_count=1,
            policy=policy,
        )
    )

    assert plan.approved is True
    assert plan.order_amount == Decimal("2000000.00")
    assert plan.quantity == Decimal("20.00000000")
    assert plan.stop_loss_price == Decimal("95000.00000000")
    assert plan.take_profit_price == Decimal("110000.00000000")
    assert plan.maximum_loss_amount == Decimal("100000.00")


def test_rejects_when_maximum_positions_reached() -> None:
    engine = RiskManagementEngine()
    policy = RiskPolicy(
        position_sizing_mode=PositionSizingMode.FIXED_AMOUNT,
        risk_per_trade_ratio=Decimal("0.01"),
        stop_loss_ratio=Decimal("0.05"),
        take_profit_ratio=Decimal("0.10"),
        maximum_position_ratio=Decimal("0.20"),
        maximum_positions=5,
        minimum_order_amount=Decimal("10000"),
        fixed_amount=Decimal("1000000"),
    )

    plan = engine.create_position_plan(
        PositionSizingRequest(
            portfolio_value=Decimal("10000000"),
            available_cash=Decimal("5000000"),
            current_price=Decimal("100000"),
            current_position_count=5,
            policy=policy,
        )
    )

    assert plan.approved is False
    assert plan.reason == "MAXIMUM_POSITION_COUNT_REACHED"


def test_stop_loss_decision() -> None:
    decision = RiskManagementEngine().evaluate_exit(
        ExitEvaluationRequest(
            entry_price=Decimal("100"),
            current_price=Decimal("94"),
            highest_price=Decimal("110"),
            stop_loss_price=Decimal("95"),
            take_profit_price=Decimal("120"),
            trailing_stop_ratio=Decimal("0.10"),
        )
    )

    assert decision.should_exit is True
    assert decision.reason == "STOP_LOSS"


def test_trailing_stop_decision() -> None:
    decision = RiskManagementEngine().evaluate_exit(
        ExitEvaluationRequest(
            entry_price=Decimal("100"),
            current_price=Decimal("107"),
            highest_price=Decimal("120"),
            stop_loss_price=Decimal("95"),
            take_profit_price=Decimal("130"),
            trailing_stop_ratio=Decimal("0.10"),
        )
    )

    assert decision.should_exit is True
    assert decision.reason == "TRAILING_STOP"
    assert decision.trigger_price == Decimal("108.00000000")
