from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.risk.allocation_service import (
    CandidatePositionPlanService,
)


router = APIRouter(
    prefix="/api/v1/position-candidates",
    tags=["Position Candidates"],
)


class BatchPositionPlanRequest(BaseModel):
    exchange_code: str = Field(
        min_length=1,
        max_length=20,
    )
    policy_id: int = Field(gt=0)
    portfolio_value: Decimal = Field(gt=0)
    available_cash: Decimal = Field(ge=0)
    current_position_count: int = Field(ge=0)
    limit: int = Field(default=5, ge=1, le=30)
    minimum_ai_score: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=100,
    )
    minimum_confidence: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=1,
    )
    allowed_actions: list[str] = Field(
        default_factory=lambda: [
            "WATCH",
            "REVIEW",
        ]
    )


@router.post("/plans")
def create_candidate_position_plans(
    request: BatchPositionPlanRequest,
    session: Session = Depends(get_db_session),
):
    service = CandidatePositionPlanService(session)

    try:
        result = service.create_plans(
            exchange_code=request.exchange_code,
            policy_id=request.policy_id,
            portfolio_value=request.portfolio_value,
            available_cash=request.available_cash,
            current_position_count=(
                request.current_position_count
            ),
            limit=request.limit,
            minimum_ai_score=request.minimum_ai_score,
            minimum_confidence=request.minimum_confidence,
            allowed_actions=set(
                request.allowed_actions
            ),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "analysis_run_id": result.analysis_run_id,
        "policy_id": result.policy_id,
        "exchange_code": result.exchange_code,
        "requested_count": result.requested_count,
        "planned_count": result.planned_count,
        "approved_count": result.approved_count,
        "rejected_count": result.rejected_count,
        "remaining_cash": result.remaining_cash,
        "candidates": [
            {
                "rank_no": item.rank_no,
                "symbol": item.symbol,
                "ai_score": item.ai_score,
                "action_code": item.action_code,
                "confidence": item.confidence,
                "current_price": item.current_price,
                "position_plan_id": (
                    item.position_plan_id
                ),
                "approved": item.approved,
                "reason_code": item.reason_code,
                "quantity": item.quantity,
                "order_amount": item.order_amount,
                "stop_loss_price": (
                    item.stop_loss_price
                ),
                "take_profit_price": (
                    item.take_profit_price
                ),
                "trailing_stop_ratio": (
                    item.trailing_stop_ratio
                ),
                "maximum_loss_amount": (
                    item.maximum_loss_amount
                ),
            }
            for item in result.candidates
        ],
    }
