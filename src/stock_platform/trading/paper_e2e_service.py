from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionResult,
    OrderExecutionService,
)
from stock_platform.order.models import (
    OrderSide,
    OrderType,
)


@dataclass(frozen=True, slots=True)
class PaperTradingE2EResult:
    submit: OrderExecutionResult
    environment: str
    live_blocked_by_default: bool


class PaperTradingE2EService:
    """
    모의투자 기본 경로 검증용 오케스트레이터.
    주문은 OrderExecutionService → Outbox만 사용한다.
    """

    def __init__(self, session: Session) -> None:
        self._execution = OrderExecutionService(session)

    def submit_paper_order(
        self,
        *,
        account_id: int,
        exchange_code: str,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        account_number: str = "PAPER",
    ) -> PaperTradingE2EResult:
        result = self._execution.submit(
            OrderExecutionCommand(
                account_id=account_id,
                broker_code="KIWOOM",
                exchange_code=exchange_code,
                symbol=symbol,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=quantity,
                price=price,
                account_number=account_number,
                skip_risk_checks=True,
                metadata_payload={
                    "environment": "PAPER",
                    "source": "PAPER_E2E",
                },
                actor="PAPER_E2E",
            )
        )
        return PaperTradingE2EResult(
            submit=result,
            environment="PAPER",
            live_blocked_by_default=True,
        )
