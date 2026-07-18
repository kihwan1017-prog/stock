from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import ExitEvaluationRequest


@dataclass(frozen=True, slots=True)
class ManagedPosition:
    account_id: int
    exchange_code: str
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal
    highest_price: Decimal
    stop_loss_price: Decimal
    take_profit_price: Decimal
    trailing_stop_ratio: Decimal | None = None
    broker_code: str = "KIWOOM"


@dataclass(frozen=True, slots=True)
class PositionExitAction:
    symbol: str
    reason: str
    trigger_price: Decimal | None
    order_id: int | None
    submitted: bool


class PositionExitMonitorService:
    """손절/익절/트레일링 조건을 평가해 청산 주문을 제출한다."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._risk_engine = RiskManagementEngine()
        self._execution = OrderExecutionService(session)

    def evaluate_and_exit(
        self,
        positions: list[ManagedPosition],
        *,
        skip_risk_checks: bool = False,
    ) -> list[PositionExitAction]:
        actions: list[PositionExitAction] = []
        for position in positions:
            decision = self._risk_engine.evaluate_exit(
                ExitEvaluationRequest(
                    entry_price=position.entry_price,
                    current_price=position.current_price,
                    highest_price=position.highest_price,
                    stop_loss_price=position.stop_loss_price,
                    take_profit_price=position.take_profit_price,
                    trailing_stop_ratio=(
                        position.trailing_stop_ratio
                    ),
                )
            )
            if not decision.should_exit:
                actions.append(
                    PositionExitAction(
                        symbol=position.symbol,
                        reason=decision.reason,
                        trigger_price=decision.trigger_price,
                        order_id=None,
                        submitted=False,
                    )
                )
                continue

            result = self._execution.submit(
                OrderExecutionCommand(
                    account_id=position.account_id,
                    broker_code=position.broker_code,
                    exchange_code=position.exchange_code,
                    symbol=position.symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=position.quantity,
                    price=position.current_price,
                    skip_risk_checks=skip_risk_checks,
                    metadata_payload={
                        "source": "POSITION_EXIT_MONITOR",
                        "exit_reason": decision.reason,
                    },
                    actor="POSITION_EXIT_MONITOR",
                    idempotency_key=(
                        f"EXIT:{position.exchange_code}:"
                        f"{position.symbol}:{decision.reason}:"
                        f"{position.quantity}"
                    ),
                )
            )
            actions.append(
                PositionExitAction(
                    symbol=position.symbol,
                    reason=decision.reason,
                    trigger_price=decision.trigger_price,
                    order_id=result.order_id,
                    submitted=result.allowed,
                )
            )
        return actions
