from __future__ import annotations

from datetime import datetime, timezone

from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskDecisionLevel,
    RiskEvaluationResult,
    RiskOrderRequest,
    RiskPolicy,
)
from stock_platform.risk_engine.rules import (
    AvailableCashRule,
    BrokerHealthRule,
    DailyLossRule,
    EmergencyStopRule,
    MarketDataFreshnessRule,
    MaximumInvestmentRatioRule,
    MaximumOpenPositionsRule,
    MaximumOrderAmountRule,
    MaximumOrderQuantityRule,
    RiskRule,
    SellQuantityRule,
    TradingTimeRule,
)


class RealtimeRiskEngine:
    def __init__(
        self,
        rules: list[RiskRule] | None = None,
    ) -> None:
        self._rules = rules or [
            EmergencyStopRule(),
            TradingTimeRule(),
            MarketDataFreshnessRule(),
            BrokerHealthRule(),
            MaximumOrderAmountRule(),
            MaximumOrderQuantityRule(),
            AvailableCashRule(),
            MaximumOpenPositionsRule(),
            MaximumInvestmentRatioRule(),
            DailyLossRule(),
            SellQuantityRule(),
        ]

    def evaluate(
        self,
        *,
        order: RiskOrderRequest,
        account: RiskAccountState,
        policy: RiskPolicy,
    ) -> RiskEvaluationResult:
        self._validate_order(order)
        results = [
            rule.evaluate(
                order=order,
                account=account,
                policy=policy,
            )
            for rule in self._rules
        ]

        if any(
            item.level == RiskDecisionLevel.BLOCK
            for item in results
        ):
            decision = RiskDecisionLevel.BLOCK
        elif any(
            item.level == RiskDecisionLevel.WARNING
            for item in results
        ):
            decision = RiskDecisionLevel.WARNING
        else:
            decision = RiskDecisionLevel.PASS

        return RiskEvaluationResult(
            decision=decision,
            allowed=decision != RiskDecisionLevel.BLOCK,
            evaluated_at=datetime.now(timezone.utc),
            order_amount=order.order_amount,
            results=results,
        )

    @staticmethod
    def _validate_order(
        order: RiskOrderRequest,
    ) -> None:
        if order.quantity <= 0:
            raise ValueError(
                "quantity must be greater than zero"
            )

        if order.price <= 0:
            raise ValueError(
                "price must be greater than zero"
            )

        if order.account_id <= 0:
            raise ValueError(
                "account_id must be greater than zero"
            )

        if not order.exchange_code.strip():
            raise ValueError(
                "exchange_code must not be empty"
            )

        if not order.symbol.strip():
            raise ValueError(
                "symbol must not be empty"
            )
