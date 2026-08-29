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


def _as_pending_sell(account) -> Decimal:
    """미체결 SELL 수량. 필드 없으면 0 (기존 테스트 호환)."""

    raw = getattr(account, "symbol_pending_sell_quantity", ZERO)
    try:
        pending = Decimal(str(raw if raw is not None else 0))
    except Exception:  # noqa: BLE001
        return ZERO
    return pending if pending > ZERO else ZERO


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
        # ENTRY 전용 — 서버가 검증한 risk-reducing EXIT는 금액 한도 미적용
        if (
            order.side == RiskOrderSide.SELL
            and getattr(order, "is_risk_reducing", False)
        ):
            return RiskRuleResult(
                rule_code="MAX_ORDER_AMOUNT",
                level=RiskDecisionLevel.PASS,
                message="EXIT skips ENTRY max_order_amount",
                detail={
                    "order_amount": str(amount),
                    "limit": str(policy.max_order_amount),
                    "exit_skip": True,
                },
            )

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
    """STEP 8-5-13 — 고정 09:00~15:20 대신 Calendar Session Phase 사용."""

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

        try:
            from stock_platform.operation.session_timeline import (
                TradingSessionPhase,
                phase_reason_code,
                resolve_krx_timeline,
            )

            timeline = resolve_krx_timeline(moment=order.requested_at)
            phase = timeline.phase_at(order.requested_at)
            is_risk_reducing = bool(
                getattr(order, "is_risk_reducing", False)
            )
            # SELL을 위험 축소로 간주 (명시 플래그 없을 때)
            if not is_risk_reducing and order.side == RiskOrderSide.SELL:
                is_risk_reducing = True

            if timeline.allows_any_order(
                order.requested_at, is_risk_reducing=is_risk_reducing
            ):
                return RiskRuleResult(
                    rule_code="TRADING_TIME",
                    level=RiskDecisionLevel.PASS,
                    message=f"Order allowed in phase {phase.value}",
                    detail={
                        "phase": phase.value,
                        "revision": timeline.revision,
                        "reason_code": phase_reason_code(phase),
                    },
                )

            reason = phase_reason_code(phase)
            if phase == TradingSessionPhase.EXIT_ONLY and not is_risk_reducing:
                reason = phase_reason_code(phase)
            return RiskRuleResult(
                rule_code="TRADING_TIME",
                level=RiskDecisionLevel.BLOCK,
                message=f"Order blocked: {reason}",
                detail={
                    "phase": phase.value,
                    "revision": timeline.revision,
                    "reason_code": reason,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return RiskRuleResult(
                rule_code="TRADING_TIME",
                level=RiskDecisionLevel.BLOCK,
                message=f"Calendar session unavailable: {exc}",
                detail={"reason_code": "CALENDAR_UNAVAILABLE"},
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

        pending = _as_pending_sell(account)
        held = Decimal(str(account.symbol_position_quantity or ZERO))
        sellable = held - pending
        if sellable < ZERO:
            sellable = ZERO

        if order.quantity <= sellable:
            return RiskRuleResult(
                rule_code="SELL_QUANTITY",
                level=RiskDecisionLevel.PASS,
                message="Held quantity is sufficient",
                detail={
                    "held_quantity": str(held),
                    "pending_sell_quantity": str(pending),
                    "sellable_quantity": str(sellable),
                },
            )

        return RiskRuleResult(
            rule_code="SELL_QUANTITY",
            level=RiskDecisionLevel.BLOCK,
            message="Sell quantity exceeds sellable holding",
            detail={
                "held_quantity": str(held),
                "pending_sell_quantity": str(pending),
                "sellable_quantity": str(sellable),
                "sell_quantity": str(order.quantity),
            },
        )


class MarketDataFreshnessRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        if not getattr(
            policy, "block_on_stale_market_data", True
        ):
            return RiskRuleResult(
                rule_code="MARKET_DATA_FRESHNESS",
                level=RiskDecisionLevel.PASS,
                message="Stale market-data check disabled",
            )
        age = order.market_data_age_seconds
        if age is None:
            return RiskRuleResult(
                rule_code="MARKET_DATA_FRESHNESS",
                level=RiskDecisionLevel.PASS,
                message="Market data age not provided",
            )
        limit = getattr(
            policy, "max_market_data_age_seconds", 30
        )
        if age <= limit:
            return RiskRuleResult(
                rule_code="MARKET_DATA_FRESHNESS",
                level=RiskDecisionLevel.PASS,
                message="Market data is fresh",
                detail={"age_seconds": age, "limit": limit},
            )
        return RiskRuleResult(
            rule_code="MARKET_DATA_FRESHNESS",
            level=RiskDecisionLevel.BLOCK,
            message="Market data is stale",
            detail={"age_seconds": age, "limit": limit},
        )


class BrokerHealthRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        if not getattr(
            policy, "block_on_broker_unstable", True
        ):
            return RiskRuleResult(
                rule_code="BROKER_HEALTH",
                level=RiskDecisionLevel.PASS,
                message="Broker health check disabled",
            )
        rate = order.broker_error_rate
        if rate is None:
            return RiskRuleResult(
                rule_code="BROKER_HEALTH",
                level=RiskDecisionLevel.PASS,
                message="Broker error rate not provided",
            )
        limit = getattr(
            policy,
            "max_broker_error_rate",
            Decimal("0.5"),
        )
        if rate <= limit:
            return RiskRuleResult(
                rule_code="BROKER_HEALTH",
                level=RiskDecisionLevel.PASS,
                message="Broker is healthy",
                detail={
                    "error_rate": str(rate),
                    "limit": str(limit),
                },
            )
        return RiskRuleResult(
            rule_code="BROKER_HEALTH",
            level=RiskDecisionLevel.BLOCK,
            message="Broker connection is unstable",
            detail={
                "error_rate": str(rate),
                "limit": str(limit),
            },
        )


class AccountTradingPermissionRule(RiskRule):
    """계좌 일시정지·매수/매도 허용·매도전용·자동매매 게이트."""

    def evaluate(self, *, order, account, policy):
        if getattr(policy, "account_paused", False):
            # 위험 축소(EXIT) 매도는 일시정지 중에도 허용
            if (
                order.side == RiskOrderSide.SELL
                and getattr(order, "is_risk_reducing", False)
            ):
                return RiskRuleResult(
                    rule_code="ACCOUNT_PAUSED",
                    level=RiskDecisionLevel.WARNING,
                    message="Account paused but risk-reducing SELL allowed",
                )
            return RiskRuleResult(
                rule_code="ACCOUNT_PAUSED",
                level=RiskDecisionLevel.BLOCK,
                message="Account trading is paused",
            )

        source = str(getattr(order, "order_source", "MANUAL")).upper()
        if (
            source == "AUTO"
            and not getattr(policy, "auto_trading_enabled", True)
        ):
            return RiskRuleResult(
                rule_code="AUTO_TRADING_DISABLED",
                level=RiskDecisionLevel.BLOCK,
                message="Auto trading is disabled for this policy",
            )

        if order.side == RiskOrderSide.BUY:
            if getattr(policy, "sell_only", False):
                return RiskRuleResult(
                    rule_code="SELL_ONLY",
                    level=RiskDecisionLevel.BLOCK,
                    message="Sell-only mode blocks new BUY orders",
                )
            if not getattr(policy, "buy_enabled", True):
                return RiskRuleResult(
                    rule_code="BUY_DISABLED",
                    level=RiskDecisionLevel.BLOCK,
                    message="BUY is disabled for this policy",
                )

        if order.side == RiskOrderSide.SELL:
            if not getattr(policy, "sell_enabled", True):
                if getattr(order, "is_risk_reducing", False):
                    return RiskRuleResult(
                        rule_code="SELL_DISABLED",
                        level=RiskDecisionLevel.WARNING,
                        message="SELL disabled but risk-reducing exit allowed",
                    )
                return RiskRuleResult(
                    rule_code="SELL_DISABLED",
                    level=RiskDecisionLevel.BLOCK,
                    message="SELL is disabled for this policy",
                )

        return RiskRuleResult(
            rule_code="ACCOUNT_TRADING_PERMISSION",
            level=RiskDecisionLevel.PASS,
            message="Trading permissions allow this order",
        )


class DailyMaxOrderAmountRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        limit = getattr(policy, "daily_max_order_amount", None)
        if limit is None:
            return RiskRuleResult(
                rule_code="DAILY_MAX_ORDER_AMOUNT",
                level=RiskDecisionLevel.PASS,
                message="Daily max order amount not configured",
            )
        if order.side == RiskOrderSide.SELL:
            return RiskRuleResult(
                rule_code="DAILY_MAX_ORDER_AMOUNT",
                level=RiskDecisionLevel.PASS,
                message="SELL does not consume daily order budget",
            )
        projected = (
            getattr(order, "daily_ordered_amount", ZERO)
            + order.order_amount
        )
        if projected <= limit:
            return RiskRuleResult(
                rule_code="DAILY_MAX_ORDER_AMOUNT",
                level=RiskDecisionLevel.PASS,
                message="Daily order amount within limit",
                detail={
                    "projected": str(projected),
                    "limit": str(limit),
                },
            )
        return RiskRuleResult(
            rule_code="DAILY_MAX_ORDER_AMOUNT",
            level=RiskDecisionLevel.BLOCK,
            message="Daily max order amount exceeded",
            detail={
                "projected": str(projected),
                "limit": str(limit),
            },
        )


class MaxTotalInvestmentAmountRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        limit = getattr(policy, "max_total_investment_amount", None)
        if limit is None or order.side == RiskOrderSide.SELL:
            return RiskRuleResult(
                rule_code="MAX_TOTAL_INVESTMENT",
                level=RiskDecisionLevel.PASS,
                message="Total investment check skipped",
            )
        projected = account.invested_amount + order.order_amount
        if projected <= limit:
            return RiskRuleResult(
                rule_code="MAX_TOTAL_INVESTMENT",
                level=RiskDecisionLevel.PASS,
                message="Total investment within limit",
            )
        return RiskRuleResult(
            rule_code="MAX_TOTAL_INVESTMENT",
            level=RiskDecisionLevel.BLOCK,
            message="Account max investment amount exceeded",
            detail={
                "projected": str(projected),
                "limit": str(limit),
            },
        )


class MaxPositionAmountRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        limit = getattr(policy, "max_position_amount", None)
        if limit is None or order.side == RiskOrderSide.SELL:
            return RiskRuleResult(
                rule_code="MAX_POSITION_AMOUNT",
                level=RiskDecisionLevel.PASS,
                message="Position amount check skipped",
            )
        projected = (
            getattr(order, "symbol_invested_amount", ZERO)
            + order.order_amount
        )
        if projected <= limit:
            return RiskRuleResult(
                rule_code="MAX_POSITION_AMOUNT",
                level=RiskDecisionLevel.PASS,
                message="Symbol position amount within limit",
            )
        return RiskRuleResult(
            rule_code="MAX_POSITION_AMOUNT",
            level=RiskDecisionLevel.BLOCK,
            message="Symbol max investment amount exceeded",
            detail={
                "projected": str(projected),
                "limit": str(limit),
            },
        )


class DuplicateBuyRule(RiskRule):
    def evaluate(self, *, order, account, policy):
        if order.side != RiskOrderSide.BUY:
            return RiskRuleResult(
                rule_code="DUPLICATE_BUY",
                level=RiskDecisionLevel.PASS,
                message="Not a BUY order",
            )
        if getattr(policy, "allow_duplicate_buy", True):
            return RiskRuleResult(
                rule_code="DUPLICATE_BUY",
                level=RiskDecisionLevel.PASS,
                message="Duplicate buy allowed",
            )
        if account.symbol_position_quantity > ZERO:
            return RiskRuleResult(
                rule_code="DUPLICATE_BUY",
                level=RiskDecisionLevel.BLOCK,
                message="Duplicate buy blocked for existing position",
            )
        return RiskRuleResult(
            rule_code="DUPLICATE_BUY",
            level=RiskDecisionLevel.PASS,
            message="No existing position for symbol",
        )

