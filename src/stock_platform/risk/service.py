from __future__ import annotations

from decimal import Decimal

from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import (
    PositionSizingMode,
    PositionSizingRequest,
    RiskPolicy,
)
from stock_platform.risk.persistence_models import (
    PositionPlanEntity,
    RiskPolicyEntity,
)
from stock_platform.risk.repository import RiskRepository


class RiskService:
    def __init__(
        self,
        repository: RiskRepository,
        engine: RiskManagementEngine | None = None,
    ) -> None:
        self._repository = repository
        self._engine = engine or RiskManagementEngine()

    def create_policy(
        self,
        *,
        policy_name: str,
        position_sizing_mode: PositionSizingMode,
        fixed_amount: Decimal | None,
        portfolio_ratio: Decimal | None,
        risk_per_trade_ratio: Decimal,
        stop_loss_ratio: Decimal,
        take_profit_ratio: Decimal,
        trailing_stop_ratio: Decimal | None,
        maximum_position_ratio: Decimal,
        maximum_positions: int,
        minimum_order_amount: Decimal,
    ) -> RiskPolicyEntity:
        entity = RiskPolicyEntity(
            policy_name=policy_name,
            position_sizing_mode=position_sizing_mode.value,
            fixed_amount=fixed_amount,
            portfolio_ratio=portfolio_ratio,
            risk_per_trade_ratio=risk_per_trade_ratio,
            stop_loss_ratio=stop_loss_ratio,
            take_profit_ratio=take_profit_ratio,
            trailing_stop_ratio=trailing_stop_ratio,
            maximum_position_ratio=maximum_position_ratio,
            maximum_positions=maximum_positions,
            minimum_order_amount=minimum_order_amount,
            is_active=True,
        )
        return self._repository.save_policy(entity)

    def create_and_save_position_plan(
        self,
        *,
        policy_id: int,
        exchange_code: str,
        symbol: str,
        portfolio_value: Decimal,
        available_cash: Decimal,
        current_price: Decimal,
        current_position_count: int,
    ) -> PositionPlanEntity:
        entity = self._repository.get_policy(policy_id)
        if entity is None:
            raise LookupError(
                f"Risk policy not found: {policy_id}"
            )

        policy = RiskPolicy(
            position_sizing_mode=PositionSizingMode(
                entity.position_sizing_mode
            ),
            fixed_amount=entity.fixed_amount,
            portfolio_ratio=entity.portfolio_ratio,
            risk_per_trade_ratio=entity.risk_per_trade_ratio,
            stop_loss_ratio=entity.stop_loss_ratio,
            take_profit_ratio=entity.take_profit_ratio,
            trailing_stop_ratio=entity.trailing_stop_ratio,
            maximum_position_ratio=entity.maximum_position_ratio,
            maximum_positions=entity.maximum_positions,
            minimum_order_amount=entity.minimum_order_amount,
        )

        plan = self._engine.create_position_plan(
            PositionSizingRequest(
                portfolio_value=portfolio_value,
                available_cash=available_cash,
                current_price=current_price,
                current_position_count=current_position_count,
                policy=policy,
            )
        )

        plan_entity = PositionPlanEntity(
            policy_id=entity.policy_id,
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            approved=plan.approved,
            reason_code=plan.reason,
            quantity=plan.quantity,
            order_amount=plan.order_amount,
            entry_price=plan.entry_price,
            stop_loss_price=plan.stop_loss_price,
            take_profit_price=plan.take_profit_price,
            trailing_stop_ratio=plan.trailing_stop_ratio,
            maximum_loss_amount=plan.maximum_loss_amount,
        )

        return self._repository.save_position_plan(plan_entity)
