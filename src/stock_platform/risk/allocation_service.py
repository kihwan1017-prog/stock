from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.ai.analysis_repository import (
    CandidateAnalysisRepository,
)
from stock_platform.markets.repository import PriceDailyRepository
from stock_platform.markets.service import PriceDailyService
from stock_platform.risk.repository import RiskRepository
from stock_platform.risk.service import RiskService


@dataclass(frozen=True, slots=True)
class PlannedCandidate:
    rank_no: int
    exchange_code: str
    symbol: str
    ai_score: Decimal
    action_code: str
    confidence: Decimal
    current_price: Decimal
    position_plan_id: int
    approved: bool
    reason_code: str
    quantity: Decimal
    order_amount: Decimal
    stop_loss_price: Decimal
    take_profit_price: Decimal
    trailing_stop_ratio: Decimal | None
    maximum_loss_amount: Decimal


@dataclass(frozen=True, slots=True)
class BatchPositionPlanResult:
    analysis_run_id: int
    policy_id: int
    exchange_code: str
    requested_count: int
    planned_count: int
    approved_count: int
    rejected_count: int
    remaining_cash: Decimal
    candidates: list[PlannedCandidate]


class CandidatePositionPlanService:
    """
    최신 AI 후보를 위험관리 정책에 연결해 주문 전 포지션 계획을
    일괄 생성하고 strategy.position_plan에 저장한다.

    실제 주문은 전송하지 않는다.
    """

    def __init__(self, session: Session) -> None:
        self._analysis_repository = (
            CandidateAnalysisRepository(session)
        )
        self._risk_repository = RiskRepository(session)
        self._risk_service = RiskService(
            self._risk_repository
        )
        self._price_service = PriceDailyService(
            PriceDailyRepository(session)
        )

    def create_plans(
        self,
        *,
        exchange_code: str,
        policy_id: int,
        portfolio_value: Decimal,
        available_cash: Decimal,
        current_position_count: int,
        limit: int = 5,
        minimum_ai_score: Decimal = Decimal("0"),
        minimum_confidence: Decimal = Decimal("0"),
        allowed_actions: set[str] | None = None,
    ) -> BatchPositionPlanResult:
        if portfolio_value <= 0:
            raise ValueError(
                "portfolio_value must be greater than zero"
            )
        if available_cash < 0:
            raise ValueError(
                "available_cash must not be negative"
            )
        if current_position_count < 0:
            raise ValueError(
                "current_position_count must not be negative"
            )
        if not 1 <= limit <= 30:
            raise ValueError(
                "limit must be between 1 and 30"
            )
        if not Decimal("0") <= minimum_ai_score <= Decimal("100"):
            raise ValueError(
                "minimum_ai_score must be between 0 and 100"
            )
        if not Decimal("0") <= minimum_confidence <= Decimal("1"):
            raise ValueError(
                "minimum_confidence must be between 0 and 1"
            )

        normalized_exchange = exchange_code.strip().upper()
        normalized_actions = {
            value.strip().upper()
            for value in (
                allowed_actions
                or {"WATCH", "REVIEW"}
            )
        }

        policy = self._risk_repository.get_policy(policy_id)
        if policy is None:
            raise LookupError(
                f"Risk policy not found: {policy_id}"
            )
        if not policy.is_active:
            raise ValueError(
                f"Risk policy is inactive: {policy_id}"
            )

        analysis_run = (
            self._analysis_repository.get_latest_run(
                exchange_code=normalized_exchange
            )
        )
        if analysis_run is None:
            raise LookupError(
                f"AI analysis not found: {normalized_exchange}"
            )

        analysis_rows = (
            self._analysis_repository.get_results(
                analysis_run.analysis_run_id
            )
        )

        eligible_rows = [
            row
            for row in analysis_rows
            if row.ai_score >= minimum_ai_score
            and row.confidence >= minimum_confidence
            and row.action_code.upper() in normalized_actions
        ][:limit]

        remaining_cash = available_cash
        position_count = current_position_count
        planned: list[PlannedCandidate] = []

        for row in eligible_rows:
            latest_price = self._price_service.get_latest(
                exchange_code=normalized_exchange,
                symbol=row.symbol,
            )

            if latest_price is None:
                continue

            current_price = Decimal(
                latest_price.close_price
            )

            plan = (
                self._risk_service
                .create_and_save_position_plan(
                    policy_id=policy_id,
                    exchange_code=normalized_exchange,
                    symbol=row.symbol,
                    portfolio_value=portfolio_value,
                    available_cash=remaining_cash,
                    current_price=current_price,
                    current_position_count=position_count,
                )
            )

            if plan.approved:
                remaining_cash -= plan.order_amount
                position_count += 1

            planned.append(
                PlannedCandidate(
                    rank_no=row.rank_no,
                    exchange_code=normalized_exchange,
                    symbol=row.symbol,
                    ai_score=row.ai_score,
                    action_code=row.action_code,
                    confidence=row.confidence,
                    current_price=current_price,
                    position_plan_id=plan.position_plan_id,
                    approved=plan.approved,
                    reason_code=plan.reason_code,
                    quantity=plan.quantity,
                    order_amount=plan.order_amount,
                    stop_loss_price=plan.stop_loss_price,
                    take_profit_price=plan.take_profit_price,
                    trailing_stop_ratio=(
                        plan.trailing_stop_ratio
                    ),
                    maximum_loss_amount=(
                        plan.maximum_loss_amount
                    ),
                )
            )

        approved_count = sum(
            1
            for item in planned
            if item.approved
        )

        return BatchPositionPlanResult(
            analysis_run_id=analysis_run.analysis_run_id,
            policy_id=policy_id,
            exchange_code=normalized_exchange,
            requested_count=len(eligible_rows),
            planned_count=len(planned),
            approved_count=approved_count,
            rejected_count=(
                len(planned) - approved_count
            ),
            remaining_cash=remaining_cash,
            candidates=planned,
        )
