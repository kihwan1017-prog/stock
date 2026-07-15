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
from stock_platform.risk_engine.position_limit_models import (
    PositionLimitPolicy,
)
from stock_platform.risk_engine.position_limit_rule import (
    DatabasePositionLimitRule,
)
from stock_platform.risk_engine.runtime import (
    realtime_risk_engine,
    realtime_risk_policy,
)


class DatabaseBackedRiskOrderGuard:
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

        position_result = DatabasePositionLimitRule(
            self._session,
            broker_code=self._broker_code,
            account_number=account_number,
            default_policy=PositionLimitPolicy(),
        ).evaluate(
            order=order,
            account=account_state,
        )

        combined_results = [
            *evaluation.results,
            position_result,
        ]

        blocked = [
            item.message
            for item in combined_results
            if item.level == RiskDecisionLevel.BLOCK
        ]

        if blocked:
            from stock_platform.risk_engine.models import (
                RiskEvaluationResult,
            )

            evaluation = RiskEvaluationResult(
                decision=RiskDecisionLevel.BLOCK,
                allowed=False,
                evaluated_at=evaluation.evaluated_at,
                order_amount=evaluation.order_amount,
                results=combined_results,
            )
        else:
            from stock_platform.risk_engine.models import (
                RiskEvaluationResult,
            )

            evaluation = RiskEvaluationResult(
                decision=evaluation.decision,
                allowed=evaluation.allowed,
                evaluated_at=evaluation.evaluated_at,
                order_amount=evaluation.order_amount,
                results=combined_results,
            )

        return RiskCheckedOrderResult(
            allowed=evaluation.allowed,
            blocked_reason=(
                "; ".join(blocked)
                if blocked
                else None
            ),
            evaluation=evaluation,
        )
