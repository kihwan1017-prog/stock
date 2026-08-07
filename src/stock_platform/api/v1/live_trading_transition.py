from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/broker/live-transition",
    tags=["Live Trading Transition"],
    # Live 전환 검증/승인 전부 admin 전용
    dependencies=[Depends(require_admin)],
)


class ValidateTransitionRequest(BaseModel):
    max_order_amount: Decimal = Field(gt=0)
    max_daily_loss: Decimal = Field(gt=0)
    paper_validation_approved: bool = False
    scope: str = Field(default="BROKER", max_length=40)
    broker_code: str | None = Field(default=None, max_length=30)
    user_broker_account_id: int | None = None


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
    reason: str | None = Field(default=None, max_length=500)
    ttl_hours: int | None = Field(default=None, ge=1, le=72)
    scope: str | None = Field(default=None, max_length=40)
    broker_code: str | None = Field(default=None, max_length=30)
    user_broker_account_id: int | None = None


class DisableTransitionRequest(BaseModel):
    reason: str = Field(
        min_length=1,
        max_length=500,
    )


@router.post("/validate")
def validate_live_transition(
    request: ValidateTransitionRequest,
    session: Session = Depends(get_db_session),
    # require_admin은 라우터 dependencies로 적용
):
    return LiveTradingTransitionService(
        session
    ).validate(
        max_order_amount=request.max_order_amount,
        max_daily_loss=request.max_daily_loss,
        paper_validation_approved=(
            request.paper_validation_approved
        ),
        scope=request.scope,
        broker_code=request.broker_code,
        user_broker_account_id=request.user_broker_account_id,
    )


@router.post("/request")
def request_live_transition(
    request: RequestTransitionRequest,
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = LiveTradingTransitionService(
        session
    ).request_transition(
        requested_by=request.requested_by,
        max_order_amount=request.max_order_amount,
        max_daily_loss=request.max_daily_loss,
        paper_validation_approved=(
            request.paper_validation_approved
        ),
        scope=request.scope,
        broker_code=request.broker_code,
        user_broker_account_id=request.user_broker_account_id,
    )
    audit.record(
        event_type="LIVE_TRANSITION_REQUEST",
        actor=request.requested_by,
        detail={
            "max_order_amount": str(
                request.max_order_amount
            ),
        },
    )
    return result


@router.post("/{transition_id}/approve")
def approve_live_transition(
    transition_id: int,
    request: ApproveTransitionRequest,
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = LiveTradingTransitionService(
            session
        ).approve_transition(
            transition_id=transition_id,
            approved_by=request.approved_by,
            approval_phrase=request.approval_phrase,
            reason=request.reason,
            ttl_hours=request.ttl_hours,
            scope=request.scope,
            broker_code=request.broker_code,
            user_broker_account_id=request.user_broker_account_id,
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

    audit.record(
        event_type="LIVE_TRANSITION_APPROVE",
        actor=request.approved_by,
        detail={"transition_id": transition_id},
    )
    return result


@router.post("/{transition_id}/disable")
def disable_live_transition(
    transition_id: int,
    request: DisableTransitionRequest,
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = LiveTradingTransitionService(
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

    audit.record(
        event_type="LIVE_TRANSITION_DISABLE",
        actor="ADMIN",
        detail={
            "transition_id": transition_id,
            "reason": request.reason,
        },
    )
    return result


class LiveDryRunRequest(BaseModel):
    user_id: int = Field(ge=1)
    user_broker_account_id: int = Field(ge=1)
    symbol: str = Field(min_length=1, max_length=30)
    side: str = Field(min_length=1, max_length=10)
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = Field(default=None, gt=0)
    broker_code: str = Field(default="KIWOOM", max_length=30)


@router.post("/dry-run")
def live_order_dry_run(
    request: LiveDryRunRequest,
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """Broker API 미호출 — LIVE 주문 흐름 Dry Run."""

    from stock_platform.broker.live_order_dry_run import (
        LiveOrderDryRunService,
    )

    result = LiveOrderDryRunService(session).run(
        user_id=request.user_id,
        user_broker_account_id=request.user_broker_account_id,
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity,
        price=request.price,
        broker_code=request.broker_code,
    )
    audit.record(
        event_type="LIVE_ORDER_DRY_RUN",
        actor="ADMIN",
        detail={
            "allowed": result.allowed,
            "blocked_by": result.blocked_by,
            "broker_endpoint_called": result.broker_endpoint_called,
            "uba": request.user_broker_account_id,
        },
    )
    return result.to_dict()


@router.get("/active")
def get_active_live_transition(
    session: Session = Depends(get_db_session),
):
    return LiveTradingTransitionService(
        session
    ).get_active()


@router.get("/history")
def list_live_transition_history(
    limit: int = 20,
    offset: int = 0,
    session: Session = Depends(get_db_session),
):
    rows = LiveTradingTransitionService(
        session
    ).list_history(limit=limit, offset=offset)
    return {
        "items": rows,
        "limit": limit,
        "offset": offset,
    }
