from decimal import Decimal
from types import SimpleNamespace

from stock_platform.risk.models import PositionSizingMode
from stock_platform.risk.service import RiskService


class FakeRepository:
    def __init__(self) -> None:
        self.saved_policy = None
        self.saved_plan = None

    def save_policy(self, entity):
        entity.policy_id = 1
        self.saved_policy = entity
        return entity

    def get_policy(self, policy_id: int):
        if policy_id != 1:
            return None

        return SimpleNamespace(
            policy_id=1,
            position_sizing_mode="RISK_BASED",
            fixed_amount=None,
            portfolio_ratio=None,
            risk_per_trade_ratio=Decimal("0.01"),
            stop_loss_ratio=Decimal("0.05"),
            take_profit_ratio=Decimal("0.10"),
            trailing_stop_ratio=Decimal("0.03"),
            maximum_position_ratio=Decimal("0.20"),
            maximum_positions=5,
            minimum_order_amount=Decimal("10000"),
        )

    def save_position_plan(self, entity):
        entity.position_plan_id = 10
        self.saved_plan = entity
        return entity


def test_create_policy() -> None:
    repo = FakeRepository()
    service = RiskService(repo)  # type: ignore[arg-type]

    entity = service.create_policy(
        policy_name="기본 정책",
        position_sizing_mode=PositionSizingMode.RISK_BASED,
        fixed_amount=None,
        portfolio_ratio=None,
        risk_per_trade_ratio=Decimal("0.01"),
        stop_loss_ratio=Decimal("0.05"),
        take_profit_ratio=Decimal("0.10"),
        trailing_stop_ratio=Decimal("0.03"),
        maximum_position_ratio=Decimal("0.20"),
        maximum_positions=5,
        minimum_order_amount=Decimal("10000"),
    )

    assert entity.policy_id == 1
    assert entity.policy_name == "기본 정책"


def test_create_and_save_position_plan() -> None:
    repo = FakeRepository()
    service = RiskService(repo)  # type: ignore[arg-type]

    entity = service.create_and_save_position_plan(
        policy_id=1,
        exchange_code="KRX",
        symbol="005930",
        portfolio_value=Decimal("10000000"),
        available_cash=Decimal("5000000"),
        current_price=Decimal("100000"),
        current_position_count=1,
    )

    assert entity.position_plan_id == 10
    assert entity.approved is True
    assert entity.symbol == "005930"
