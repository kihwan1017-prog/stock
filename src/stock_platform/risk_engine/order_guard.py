from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.risk_engine.account_state_service import (
    RiskAccountStateService,
)
from stock_platform.risk_engine.integration_models import (
    RiskCheckedOrderResult,
)
from stock_platform.risk_engine.models import (
    RiskDecisionLevel,
    RiskOrderRequest,
    RiskOrderSide,
)
from stock_platform.risk_engine.runtime import (
    realtime_risk_engine,
    realtime_risk_policy,
)


class DatabaseBackedRiskOrderGuard:
    """DB 계좌 상태를 읽어 주문 전 Risk Engine 검사를 수행한다."""

    def __init__(
        self,
        session: Session,
        *,
        broker_code: str = "KIWOOM",
    ) -> None:
        self._session = session
        self._broker_code = broker_code
        self._account_state_service = (
            RiskAccountStateService(session)
        )

    def check(
        self,
        *,
        account_number: str,
        account_id: int,
        exchange_code: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
    ) -> RiskCheckedOrderResult:
        account_state = self._account_state_service.load(
            broker_code=self._broker_code,
            account_number=account_number,
            exchange_code=exchange_code,
            symbol=symbol,
        )

        order = RiskOrderRequest(
            exchange_code=exchange_code,
            symbol=symbol,
            side=RiskOrderSide(side.upper()),
            quantity=quantity,
            price=price,
            account_id=account_id,
            requested_at=datetime.now(timezone.utc),
        )

        evaluation = realtime_risk_engine.evaluate(
            order=order,
            account=account_state,
            policy=realtime_risk_policy,
        )

        blocked = [
            item.message
            for item in evaluation.results
            if item.level == RiskDecisionLevel.BLOCK
        ]

        return RiskCheckedOrderResult(
            allowed=evaluation.allowed,
            blocked_reason=(
                "; ".join(blocked)
                if blocked
                else None
            ),
            evaluation=evaluation,
        )
