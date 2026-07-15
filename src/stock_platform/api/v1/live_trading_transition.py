from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/broker/live-transition",
    tags=["Live Trading Transition"],
)


class ValidateTransitionRequest(BaseModel):
    max_order_amount: Decimal = Field(gt=0)
    max_daily_loss: Decimal = Field(gt=0)
    paper_validation_approved: bool = False


class RequestTransitionRequest(
    ValidateTransitionRequest
):
    requested_by: str = Field(
        min_length=1,
        max_length=100,
    )


class ApproveTransitionRequest(BaseModel):
    approved_by: str = Field(
        min_length=1,
        max_length=100,
    )
    approval_phrase: str = Field(
        min_length=1,
        max_length=100,
    )


class DisableTransitionRequest(BaseModel):
    reason: str = Field(
        min_length=1,
        max_length=500,
    )


@router.post("/validate")
def validate_live_transition(
    request: ValidateTransitionRequest,
    session: Session = Depends(get_db_session),
):
    return LiveTradingTransitionService(
        session
    ).validate(
        max_order_amount=request.max_order_amount,
        max_daily_loss=request.max_daily_loss,
        paper_validation_approved=(
            request.paper_validation_approved
        ),
    )


@router.post("/request")
def request_live_transition(
    request: RequestTransitionRequest,
    session: Session = Depends(get_db_session),
):
    return LiveTradingTransitionService(
        session
    ).request_transition(
        requested_by=request.requested_by,
        max_order_amount=request.max_order_amount,
        max_daily_loss=request.max_daily_loss,
        paper_validation_approved=(
            request.paper_validation_approved
        ),
    )


@router.post("/{transition_id}/approve")
def approve_live_transition(
    transition_id: int,
    request: ApproveTransitionRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return LiveTradingTransitionService(
            session
        ).approve_transition(
            transition_id=transition_id,
            approved_by=request.approved_by,
            approval_phrase=request.approval_phrase,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.post("/{transition_id}/disable")
def disable_live_transition(
    transition_id: int,
    request: DisableTransitionRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return LiveTradingTransitionService(
            session
        ).disable_transition(
            transition_id=transition_id,
            reason=request.reason,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/active")
def get_active_live_transition(
    session: Session = Depends(get_db_session),
):
    return LiveTradingTransitionService(
        session
    ).get_active()
