"""STEP32 호환용 인메모리 리스크 게이트.

본선은 `RiskService`(DB) + `risk_engine` 을 사용한다.
"""

from __future__ import annotations

from stock_platform.risk.models import (
    RiskDecision,
    RiskLimits,
    RiskRequest,
)


class InMemoryRiskGate:
    """레거시 한도 검사. Deprecated API `/risk/check` 전용."""

    def __init__(
        self,
        limits: RiskLimits,
        kill_switch_enabled: bool = False,
    ) -> None:
        self.limits = limits
        self.kill_switch_enabled = kill_switch_enabled

    def evaluate(self, request: RiskRequest) -> RiskDecision:
        reasons: list[str] = []
        if self.kill_switch_enabled:
            reasons.append("KILL_SWITCH_ENABLED")
        if request.order_amount > self.limits.max_order_amount:
            reasons.append("MAX_ORDER_AMOUNT_EXCEEDED")
        if (
            request.current_position_amount
            + request.order_amount
            > self.limits.max_position_amount
        ):
            reasons.append("MAX_POSITION_AMOUNT_EXCEEDED")
        if (
            request.daily_realized_pnl
            <= -self.limits.max_daily_loss
        ):
            reasons.append("MAX_DAILY_LOSS_EXCEEDED")
        if (
            request.creates_new_position
            and request.open_positions
            >= self.limits.max_open_positions
        ):
            reasons.append("MAX_OPEN_POSITIONS_EXCEEDED")
        return RiskDecision(not reasons, tuple(reasons))
