from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timezone
from decimal import Decimal

from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskDecisionLevel,
    RiskOrderRequest,
    RiskOrderSide,
    RiskPolicy,
    RiskRuleResult,
)


ZERO = Decimal("0")


class RiskRule(ABC):
    @abstractmethod
    def evaluate(
        self,
        *,
        order: RiskOrderRequest,
        account: RiskAccountState,
        policy: RiskPolicy,
    ) -> RiskRuleResult:
        raise NotImplementedError


class EmergencyStopRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        if not policy.emergency_stop_enabled:
            return RiskRuleResult(
                rule_code="EMERGENCY_STOP",
                level=RiskDecisionLevel.PASS,
                message="Emergency stop is disabled",
            )

        if (
            order.side == RiskOrderSide.SELL
            and policy.allow_sell_during_emergency_stop
        ):
            return RiskRuleResult(
                rule_code="EMERGENCY_STOP",
                level=RiskDecisionLevel.WARNING,
                message=(
                    "Emergency stop is active, but SELL is "
                    "allowed for risk reduction"
                ),
            )

        return RiskRuleResult(
            rule_code="EMERGENCY_STOP",
            level=RiskDecisionLevel.BLOCK,
            message="Emergency stop is active",
        )


class MaximumOrderAmountRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        amount = order.order_amount

        if amount <= policy.max_order_amount:
            return RiskRuleResult(
                rule_code="MAX_ORDER_AMOUNT",
                level=RiskDecisionLevel.PASS,
                message="Order amount is within limit",
                detail={
                    "order_amount": str(amount),
                    "limit": str(policy.max_order_amount),
                },
            )

        return RiskRuleResult(
            rule_code="MAX_ORDER_AMOUNT",
            level=RiskDecisionLevel.BLOCK,
            message="Order amount exceeds configured limit",
            detail={
                "order_amount": str(amount),
                "limit": str(policy.max_order_amount),
            },
        )


class MaximumOrderQuantityRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        if order.quantity <= policy.max_order_quantity:
            return RiskRuleResult(
                rule_code="MAX_ORDER_QUANTITY",
                level=RiskDecisionLevel.PASS,
                message="Order quantity is within limit",
            )

        return RiskRuleResult(
            rule_code="MAX_ORDER_QUANTITY",
            level=RiskDecisionLevel.BLOCK,
            message="Order quantity exceeds configured limit",
            detail={
                "quantity": str(order.quantity),
                "limit": str(policy.max_order_quantity),
            },
        )


class MaximumOpenPositionsRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        is_new_position = (
            order.side == RiskOrderSide.BUY
            and account.symbol_position_quantity <= ZERO
        )

        if not is_new_position:
            return RiskRuleResult(
                rule_code="MAX_OPEN_POSITIONS",
                level=RiskDecisionLevel.PASS,
                message="Order does not create a new position",
            )

        if account.open_position_count < policy.max_open_positions:
            return RiskRuleResult(
                rule_code="MAX_OPEN_POSITIONS",
                level=RiskDecisionLevel.PASS,
                message="Open position count is within limit",
            )

        return RiskRuleResult(
            rule_code="MAX_OPEN_POSITIONS",
            level=RiskDecisionLevel.BLOCK,
            message="Maximum open position count reached",
            detail={
                "open_position_count": (
                    account.open_position_count
                ),
                "limit": policy.max_open_positions,
            },
        )


class MaximumInvestmentRatioRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        if order.side == RiskOrderSide.SELL:
            return RiskRuleResult(
                rule_code="MAX_INVESTMENT_RATIO",
                level=RiskDecisionLevel.PASS,
                message="SELL reduces investment exposure",
            )

        if account.total_asset_value <= ZERO:
            return RiskRuleResult(
                rule_code="MAX_INVESTMENT_RATIO",
                level=RiskDecisionLevel.BLOCK,
                message="Total asset value must be greater than zero",
            )

        projected = account.invested_amount + order.order_amount
        ratio = projected / account.total_asset_value

        if ratio <= policy.max_investment_ratio:
            return RiskRuleResult(
                rule_code="MAX_INVESTMENT_RATIO",
                level=RiskDecisionLevel.PASS,
                message="Projected investment ratio is within limit",
                detail={
                    "projected_ratio": str(ratio),
                    "limit": str(policy.max_investment_ratio),
                },
            )

        return RiskRuleResult(
            rule_code="MAX_INVESTMENT_RATIO",
            level=RiskDecisionLevel.BLOCK,
            message="Projected investment ratio exceeds limit",
            detail={
                "projected_ratio": str(ratio),
                "limit": str(policy.max_investment_ratio),
            },
        )


class DailyLossRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        combined_profit_loss = (
            account.daily_realized_profit_loss
            + account.daily_unrealized_profit_loss
        )
        current_loss = max(-combined_profit_loss, ZERO)

        if current_loss < policy.max_daily_loss:
            return RiskRuleResult(
                rule_code="DAILY_LOSS",
                level=RiskDecisionLevel.PASS,
                message="Daily loss is within limit",
                detail={
                    "current_loss": str(current_loss),
                    "limit": str(policy.max_daily_loss),
                },
            )

        if order.side == RiskOrderSide.SELL:
            return RiskRuleResult(
                rule_code="DAILY_LOSS",
                level=RiskDecisionLevel.WARNING,
                message=(
                    "Daily loss limit reached, but SELL is "
                    "allowed for exposure reduction"
                ),
                detail={
                    "current_loss": str(current_loss),
                    "limit": str(policy.max_daily_loss),
                },
            )

        return RiskRuleResult(
            rule_code="DAILY_LOSS",
            level=RiskDecisionLevel.BLOCK,
            message="Daily loss limit reached",
            detail={
                "current_loss": str(current_loss),
                "limit": str(policy.max_daily_loss),
            },
        )


class TradingTimeRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        if (
            order.exchange_code.upper() != "KRX"
            or not policy.enforce_krx_market_hours
        ):
            return RiskRuleResult(
                rule_code="TRADING_TIME",
                level=RiskDecisionLevel.PASS,
                message="Market-hour check is not required",
            )

        local_time = (
            order.requested_at
            .astimezone()
            .time()
            .replace(tzinfo=None)
        )

        if (
            policy.trading_start_time
            <= local_time
            <= policy.trading_end_time
        ):
            return RiskRuleResult(
                rule_code="TRADING_TIME",
                level=RiskDecisionLevel.PASS,
                message="Order is within configured trading hours",
            )

        return RiskRuleResult(
            rule_code="TRADING_TIME",
            level=RiskDecisionLevel.BLOCK,
            message="Order is outside configured trading hours",
            detail={
                "requested_time": local_time.isoformat(),
                "start_time": (
                    policy.trading_start_time.isoformat()
                ),
                "end_time": (
                    policy.trading_end_time.isoformat()
                ),
            },
        )


class AvailableCashRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        if order.side == RiskOrderSide.SELL:
            return RiskRuleResult(
                rule_code="AVAILABLE_CASH",
                level=RiskDecisionLevel.PASS,
                message="SELL does not require additional cash",
            )

        if order.order_amount <= account.cash_balance:
            return RiskRuleResult(
                rule_code="AVAILABLE_CASH",
                level=RiskDecisionLevel.PASS,
                message="Cash balance is sufficient",
            )

        return RiskRuleResult(
            rule_code="AVAILABLE_CASH",
            level=RiskDecisionLevel.BLOCK,
            message="Insufficient cash balance",
            detail={
                "cash_balance": str(account.cash_balance),
                "order_amount": str(order.order_amount),
            },
        )


class SellQuantityRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        if order.side == RiskOrderSide.BUY:
            return RiskRuleResult(
                rule_code="SELL_QUANTITY",
                level=RiskDecisionLevel.PASS,
                message="BUY does not require held quantity",
            )

        if order.quantity <= account.symbol_position_quantity:
            return RiskRuleResult(
                rule_code="SELL_QUANTITY",
                level=RiskDecisionLevel.PASS,
                message="Held quantity is sufficient",
            )

        return RiskRuleResult(
            rule_code="SELL_QUANTITY",
            level=RiskDecisionLevel.BLOCK,
            message="Sell quantity exceeds held quantity",
            detail={
                "held_quantity": str(
                    account.symbol_position_quantity
                ),
                "sell_quantity": str(order.quantity),
            },
        )
