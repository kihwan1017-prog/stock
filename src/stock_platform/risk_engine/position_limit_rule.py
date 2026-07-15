from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskDecisionLevel,
    RiskOrderRequest,
    RiskOrderSide,
    RiskRuleResult,
)
from stock_platform.risk_engine.position_limit_models import (
    PositionLimitPolicy,
)
from stock_platform.risk_engine.position_limit_repository import (
    PositionLimitRepository,
)


ZERO = Decimal("0")


class DatabasePositionLimitRule:
    def __init__(
        self,
        session: Session,
        *,
        broker_code: str,
        account_number: str,
        default_policy: PositionLimitPolicy,
    ) -> None:
        self._repository = PositionLimitRepository(session)
        self._broker_code = broker_code
        self._account_number = account_number
        self._default_policy = default_policy

    def evaluate(
        self,
        *,
        order: RiskOrderRequest,
        account: RiskAccountState,
    ) -> RiskRuleResult:
        if order.side == RiskOrderSide.SELL:
            return RiskRuleResult(
                rule_code="POSITION_LIMIT",
                level=RiskDecisionLevel.PASS,
                message="SELL reduces position exposure",
            )

        entity = self._repository.get(
            broker_code=self._broker_code,
            account_number=self._account_number,
            exchange_code=order.exchange_code,
            symbol=order.symbol,
        )

        max_quantity = (
            Decimal(entity.max_quantity)
            if entity is not None
            else self._default_policy.max_symbol_quantity
        )
        max_amount = (
            Decimal(entity.max_position_amount)
            if entity is not None
            else self._default_policy.max_symbol_amount
        )
        max_weight = (
            Decimal(entity.max_position_weight)
            if entity is not None
            else self._default_policy.max_symbol_weight
        )

        projected_quantity = (
            account.symbol_position_quantity + order.quantity
        )
        projected_amount = (
            account.symbol_position_quantity * order.price
            + order.order_amount
        )
        projected_weight = (
            projected_amount / account.total_asset_value
            if account.total_asset_value > ZERO
            else Decimal("1")
        )

        blocked: list[str] = []

        if projected_quantity > max_quantity:
            blocked.append("quantity")

        if projected_amount > max_amount:
            blocked.append("amount")

        if projected_weight > max_weight:
            blocked.append("weight")

        if blocked:
            return RiskRuleResult(
                rule_code="POSITION_LIMIT",
                level=RiskDecisionLevel.BLOCK,
                message=(
                    "Projected symbol position exceeds "
                    + ", ".join(blocked)
                    + " limit"
                ),
                detail={
                    "projected_quantity": str(
                        projected_quantity
                    ),
                    "max_quantity": str(max_quantity),
                    "projected_amount": str(
                        projected_amount
                    ),
                    "max_amount": str(max_amount),
                    "projected_weight": str(
                        projected_weight
                    ),
                    "max_weight": str(max_weight),
                },
            )

        return RiskRuleResult(
            rule_code="POSITION_LIMIT",
            level=RiskDecisionLevel.PASS,
            message="Projected symbol position is within limits",
            detail={
                "projected_quantity": str(
                    projected_quantity
                ),
                "projected_amount": str(
                    projected_amount
                ),
                "projected_weight": str(
                    projected_weight
                ),
            },
        )
