from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from stock_platform.risk.models import (
    ExitDecision,
    ExitEvaluationRequest,
    PositionPlan,
    PositionSizingMode,
    PositionSizingRequest,
    RiskPolicy,
)


ZERO = Decimal("0")
ONE = Decimal("1")


class RiskValidationError(ValueError):
    """Raised when a risk request or policy is invalid."""


class RiskManagementEngine:
    """주문 전 포지션 크기와 청산 조건을 계산한다."""

    def create_position_plan(
        self,
        request: PositionSizingRequest,
    ) -> PositionPlan:
        self._validate_request(request)

        policy = request.policy

        if request.current_position_count >= policy.maximum_positions:
            return self._rejected_plan(
                request=request,
                reason="MAXIMUM_POSITION_COUNT_REACHED",
            )

        maximum_position_amount = (
            request.portfolio_value
            * policy.maximum_position_ratio
        )
        requested_amount = self._calculate_requested_amount(
            request=request
        )
        order_amount = min(
            requested_amount,
            maximum_position_amount,
            request.available_cash,
        )

        if order_amount < policy.minimum_order_amount:
            return self._rejected_plan(
                request=request,
                reason="ORDER_AMOUNT_BELOW_MINIMUM",
            )

        quantity = (
            order_amount / request.current_price
        ).quantize(
            Decimal("0.00000001"),
            rounding=ROUND_DOWN,
        )

        actual_order_amount = (
            quantity * request.current_price
        ).quantize(Decimal("0.01"))

        if quantity <= ZERO:
            return self._rejected_plan(
                request=request,
                reason="QUANTITY_IS_ZERO",
            )

        stop_loss_price = (
            request.current_price
            * (ONE - policy.stop_loss_ratio)
        ).quantize(Decimal("0.00000001"))

        take_profit_price = (
            request.current_price
            * (ONE + policy.take_profit_ratio)
        ).quantize(Decimal("0.00000001"))

        maximum_loss_amount = (
            actual_order_amount
            * policy.stop_loss_ratio
        ).quantize(Decimal("0.01"))

        return PositionPlan(
            approved=True,
            reason="APPROVED",
            quantity=quantity,
            order_amount=actual_order_amount,
            entry_price=request.current_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            trailing_stop_ratio=policy.trailing_stop_ratio,
            maximum_loss_amount=maximum_loss_amount,
        )

    def evaluate_exit(
        self,
        request: ExitEvaluationRequest,
    ) -> ExitDecision:
        self._validate_exit_request(request)

        if request.current_price <= request.stop_loss_price:
            return ExitDecision(
                should_exit=True,
                reason="STOP_LOSS",
                trigger_price=request.stop_loss_price,
            )

        if request.current_price >= request.take_profit_price:
            return ExitDecision(
                should_exit=True,
                reason="TAKE_PROFIT",
                trigger_price=request.take_profit_price,
            )

        if request.trailing_stop_ratio is not None:
            trailing_trigger = (
                request.highest_price
                * (ONE - request.trailing_stop_ratio)
            )

            if (
                request.highest_price > request.entry_price
                and request.current_price <= trailing_trigger
            ):
                return ExitDecision(
                    should_exit=True,
                    reason="TRAILING_STOP",
                    trigger_price=trailing_trigger.quantize(
                        Decimal("0.00000001")
                    ),
                )

        return ExitDecision(
            should_exit=False,
            reason="HOLD",
            trigger_price=None,
        )

    def _calculate_requested_amount(
        self,
        *,
        request: PositionSizingRequest,
    ) -> Decimal:
        policy = request.policy

        if (
            policy.position_sizing_mode
            == PositionSizingMode.FIXED_AMOUNT
        ):
            if policy.fixed_amount is None:
                raise RiskValidationError(
                    "fixed_amount is required"
                )
            return policy.fixed_amount

        if (
            policy.position_sizing_mode
            == PositionSizingMode.FIXED_RATIO
        ):
            if policy.portfolio_ratio is None:
                raise RiskValidationError(
                    "portfolio_ratio is required"
                )
            return (
                request.portfolio_value
                * policy.portfolio_ratio
            )

        if (
            policy.position_sizing_mode
            == PositionSizingMode.RISK_BASED
        ):
            risk_budget = (
                request.portfolio_value
                * policy.risk_per_trade_ratio
            )
            return risk_budget / policy.stop_loss_ratio

        raise RiskValidationError(
            "Unsupported position_sizing_mode"
        )

    @staticmethod
    def _validate_request(
        request: PositionSizingRequest,
    ) -> None:
        if request.portfolio_value <= ZERO:
            raise RiskValidationError(
                "portfolio_value must be greater than zero"
            )
        if request.available_cash < ZERO:
            raise RiskValidationError(
                "available_cash must not be negative"
            )
        if request.current_price <= ZERO:
            raise RiskValidationError(
                "current_price must be greater than zero"
            )
        if request.current_position_count < 0:
            raise RiskValidationError(
                "current_position_count must not be negative"
            )

        RiskManagementEngine._validate_policy(
            request.policy
        )

    @staticmethod
    def _validate_policy(policy: RiskPolicy) -> None:
        ratio_fields = {
            "risk_per_trade_ratio": (
                policy.risk_per_trade_ratio
            ),
            "stop_loss_ratio": policy.stop_loss_ratio,
            "take_profit_ratio": policy.take_profit_ratio,
            "maximum_position_ratio": (
                policy.maximum_position_ratio
            ),
        }

        for field_name, value in ratio_fields.items():
            if value <= ZERO or value > ONE:
                raise RiskValidationError(
                    f"{field_name} must be between 0 and 1"
                )

        if policy.trailing_stop_ratio is not None:
            if (
                policy.trailing_stop_ratio <= ZERO
                or policy.trailing_stop_ratio > ONE
            ):
                raise RiskValidationError(
                    "trailing_stop_ratio must be "
                    "between 0 and 1"
                )

        if policy.maximum_positions <= 0:
            raise RiskValidationError(
                "maximum_positions must be greater than zero"
            )

        if policy.minimum_order_amount < ZERO:
            raise RiskValidationError(
                "minimum_order_amount must not be negative"
            )

    @staticmethod
    def _validate_exit_request(
        request: ExitEvaluationRequest,
    ) -> None:
        price_fields = {
            "entry_price": request.entry_price,
            "current_price": request.current_price,
            "highest_price": request.highest_price,
            "stop_loss_price": request.stop_loss_price,
            "take_profit_price": request.take_profit_price,
        }

        for field_name, value in price_fields.items():
            if value <= ZERO:
                raise RiskValidationError(
                    f"{field_name} must be greater than zero"
                )

        if request.highest_price < request.entry_price:
            raise RiskValidationError(
                "highest_price must not be below entry_price"
            )

    @staticmethod
    def _rejected_plan(
        *,
        request: PositionSizingRequest,
        reason: str,
    ) -> PositionPlan:
        return PositionPlan(
            approved=False,
            reason=reason,
            quantity=ZERO,
            order_amount=ZERO,
            entry_price=request.current_price,
            stop_loss_price=ZERO,
            take_profit_price=ZERO,
            trailing_stop_ratio=(
                request.policy.trailing_stop_ratio
            ),
            maximum_loss_amount=ZERO,
        )
