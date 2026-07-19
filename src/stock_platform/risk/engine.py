from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

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
    """위험관리 요청 또는 정책이 올바르지 않을 때 발생한다."""


class RiskManagementEngine:
    """주문 수량과 손절, 익절, 트레일링 스톱 조건을 계산한다."""

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

        max_total_ratio = getattr(
            policy,
            "maximum_total_invested_ratio",
            Decimal("1"),
        )
        if max_total_ratio < ONE:
            invested = request.invested_amount
            if (
                invested / request.portfolio_value
                >= max_total_ratio
            ):
                return self._rejected_plan(
                    request=request,
                    reason="MAXIMUM_TOTAL_INVESTED_REACHED",
                )

        maximum_position_amount = (
            request.portfolio_value
            * policy.maximum_position_ratio
        )

        requested_amount = self._calculate_requested_amount(
            request=request,
        )

        remaining_investable = (
            request.portfolio_value * max_total_ratio
            - request.invested_amount
        )
        if remaining_investable < ZERO:
            remaining_investable = ZERO

        order_amount = min(
            requested_amount,
            maximum_position_amount,
            request.available_cash,
        )
        if max_total_ratio < ONE:
            order_amount = min(
                order_amount,
                remaining_investable,
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

        if request.apply_krx_lot_rounding:
            from stock_platform.position.lot_rounding import (
                round_share_quantity,
            )

            quantity = round_share_quantity(quantity)

        actual_order_amount = (
            quantity * request.current_price
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )

        if quantity <= ZERO:
            return self._rejected_plan(
                request=request,
                reason="QUANTITY_IS_ZERO",
            )

        if actual_order_amount < policy.minimum_order_amount:
            return self._rejected_plan(
                request=request,
                reason="ORDER_AMOUNT_BELOW_MINIMUM",
            )

        if request.stop_price is not None and request.stop_price > ZERO:
            stop_loss_price = request.stop_price
        else:
            stop_loss_price = (
                request.current_price
                * (ONE - policy.stop_loss_ratio)
            ).quantize(
                Decimal("0.00000001"),
                rounding=ROUND_DOWN,
            )

        take_profit_price = (
            request.current_price
            * (ONE + policy.take_profit_ratio)
        ).quantize(
            Decimal("0.00000001"),
            rounding=ROUND_DOWN,
        )

        risk_per_share = (
            request.current_price - stop_loss_price
        )
        if risk_per_share <= ZERO:
            maximum_loss_amount = (
                actual_order_amount * policy.stop_loss_ratio
            ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        else:
            maximum_loss_amount = (
                quantity * risk_per_share
            ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

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

        # 기존 SL/TP와 별도로 상대 손실 비율을 유지·검사한다.
        if request.relative_loss_ratio is not None:
            loss_ratio = (
                (request.entry_price - request.current_price)
                / request.entry_price
            )
            if loss_ratio >= request.relative_loss_ratio:
                return ExitDecision(
                    should_exit=True,
                    reason="RELATIVE_LOSS",
                    trigger_price=request.current_price,
                )

        if request.trailing_stop_ratio is not None:
            trailing_trigger = (
                request.highest_price
                * (ONE - request.trailing_stop_ratio)
            ).quantize(
                Decimal("0.00000001"),
                rounding=ROUND_DOWN,
            )

            if (
                request.highest_price > request.entry_price
                and request.current_price <= trailing_trigger
            ):
                return ExitDecision(
                    should_exit=True,
                    reason="TRAILING_STOP",
                    trigger_price=trailing_trigger,
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
                    "fixed_amount is required",
                )

            if policy.fixed_amount <= ZERO:
                raise RiskValidationError(
                    "fixed_amount must be greater than zero",
                )

            return policy.fixed_amount

        if (
            policy.position_sizing_mode
            == PositionSizingMode.FIXED_RATIO
        ):
            if policy.portfolio_ratio is None:
                raise RiskValidationError(
                    "portfolio_ratio is required",
                )

            if (
                policy.portfolio_ratio <= ZERO
                or policy.portfolio_ratio > ONE
            ):
                raise RiskValidationError(
                    "portfolio_ratio must be between 0 and 1",
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
            if (
                request.stop_price is not None
                and request.stop_price > ZERO
                and request.stop_price < request.current_price
            ):
                risk_per_share = (
                    request.current_price - request.stop_price
                )
                quantity = (
                    risk_budget / risk_per_share
                ).quantize(
                    Decimal("0.00000001"),
                    rounding=ROUND_DOWN,
                )
                return (
                    quantity * request.current_price
                ).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_DOWN,
                )

            return risk_budget / policy.stop_loss_ratio

        raise RiskValidationError(
            "Unsupported position_sizing_mode",
        )

    @staticmethod
    def _validate_request(
        request: PositionSizingRequest,
    ) -> None:
        if request.portfolio_value <= ZERO:
            raise RiskValidationError(
                "portfolio_value must be greater than zero",
            )

        if request.available_cash < ZERO:
            raise RiskValidationError(
                "available_cash must not be negative",
            )

        if request.current_price <= ZERO:
            raise RiskValidationError(
                "current_price must be greater than zero",
            )

        if request.current_position_count < 0:
            raise RiskValidationError(
                "current_position_count must not be negative",
            )

        RiskManagementEngine._validate_policy(
            request.policy,
        )

    @staticmethod
    def _validate_policy(
        policy: RiskPolicy,
    ) -> None:
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
                    f"{field_name} must be between 0 and 1",
                )

        if policy.trailing_stop_ratio is not None:
            if (
                policy.trailing_stop_ratio <= ZERO
                or policy.trailing_stop_ratio > ONE
            ):
                raise RiskValidationError(
                    "trailing_stop_ratio must be between 0 and 1",
                )

        if policy.maximum_positions <= 0:
            raise RiskValidationError(
                "maximum_positions must be greater than zero",
            )

        if policy.minimum_order_amount < ZERO:
            raise RiskValidationError(
                "minimum_order_amount must not be negative",
            )

        max_total = getattr(
            policy,
            "maximum_total_invested_ratio",
            ONE,
        )
        if max_total <= ZERO or max_total > ONE:
            raise RiskValidationError(
                "maximum_total_invested_ratio must be between 0 and 1",
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
                    f"{field_name} must be greater than zero",
                )

        if request.highest_price < request.entry_price:
            raise RiskValidationError(
                "highest_price must not be below entry_price",
            )

        if request.stop_loss_price >= request.entry_price:
            raise RiskValidationError(
                "stop_loss_price must be below entry_price",
            )

        if request.take_profit_price <= request.entry_price:
            raise RiskValidationError(
                "take_profit_price must be above entry_price",
            )

        if request.trailing_stop_ratio is not None:
            if (
                request.trailing_stop_ratio <= ZERO
                or request.trailing_stop_ratio > ONE
            ):
                raise RiskValidationError(
                    "trailing_stop_ratio must be between 0 and 1",
                )

        if request.relative_loss_ratio is not None:
            if (
                request.relative_loss_ratio <= ZERO
                or request.relative_loss_ratio > ONE
            ):
                raise RiskValidationError(
                    "relative_loss_ratio must be between 0 and 1",
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
