"""STEP 8-5-19 — RiskService persistence 복구 테스트."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from stock_platform.risk.models import PositionSizingMode
from stock_platform.risk.service import RiskService


class FakeRiskRepository:
    def __init__(self) -> None:
        self.policies: dict[int, SimpleNamespace] = {}
        self.plans: list[SimpleNamespace] = []
        self._next_policy_id = 1
        self._next_plan_id = 1

    def save_policy(self, entity):
        entity.policy_id = self._next_policy_id
        self._next_policy_id += 1
        self.policies[entity.policy_id] = entity
        return entity

    def get_policy(self, policy_id: int):
        return self.policies.get(policy_id)

    def save_position_plan(self, entity):
        entity.position_plan_id = self._next_plan_id
        self._next_plan_id += 1
        self.plans.append(entity)
        return entity


def test_create_policy() -> None:
    repo = FakeRiskRepository()
    service = RiskService(repository=repo)

    policy = service.create_policy(
        policy_name="step8-5-19-policy",
        position_sizing_mode=PositionSizingMode.FIXED_AMOUNT,
        fixed_amount=Decimal("1000000"),
        portfolio_ratio=None,
        risk_per_trade_ratio=Decimal("0.01"),
        stop_loss_ratio=Decimal("0.03"),
        take_profit_ratio=Decimal("0.06"),
        trailing_stop_ratio=Decimal("0.02"),
        maximum_position_ratio=Decimal("0.2"),
        maximum_positions=5,
        minimum_order_amount=Decimal("10000"),
    )

    assert policy.policy_id == 1
    assert policy.policy_name == "step8-5-19-policy"
    assert policy.is_active is True
    assert repo.get_policy(1) is policy


def test_create_and_save_position_plan() -> None:
    repo = FakeRiskRepository()
    service = RiskService(repository=repo)
    policy = service.create_policy(
        policy_name="step8-5-19-plan-policy",
        position_sizing_mode=PositionSizingMode.FIXED_AMOUNT,
        fixed_amount=Decimal("1000000"),
        portfolio_ratio=None,
        risk_per_trade_ratio=Decimal("0.01"),
        stop_loss_ratio=Decimal("0.03"),
        take_profit_ratio=Decimal("0.06"),
        trailing_stop_ratio=None,
        maximum_position_ratio=Decimal("0.5"),
        maximum_positions=10,
        minimum_order_amount=Decimal("10000"),
    )

    plan = service.create_and_save_position_plan(
        policy_id=policy.policy_id,
        exchange_code="KRX",
        symbol="005930",
        portfolio_value=Decimal("10000000"),
        available_cash=Decimal("5000000"),
        current_price=Decimal("70000"),
        current_position_count=0,
    )

    assert plan.position_plan_id == 1
    assert plan.policy_id == policy.policy_id
    assert plan.symbol == "005930"
    assert plan.exchange_code == "KRX"
    assert plan.approved is True
    assert Decimal(plan.quantity) > 0
    assert len(repo.plans) == 1
