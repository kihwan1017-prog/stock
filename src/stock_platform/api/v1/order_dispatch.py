from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.broker.dispatcher import OrderDispatcher
from stock_platform.database.session import get_db_session

router = APIRouter(prefix="/api/v1/orders", tags=["Order Dispatch"])


class DispatchOrderRequest(BaseModel):
    actor: str = "API"


@router.post("/{order_id}/dispatch")
def dispatch_order(
    order_id: int,
    request: DispatchOrderRequest,
    _: str = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """기존 주문을 Outbox에 적재한다 (Broker 직접 호출 금지)."""
    try:
        result = OrderDispatcher(session).dispatch(
            order_id,
            request.actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit.record(
        event_type="ORDER_DISPATCH",
        actor=request.actor,
        order_id=order_id,
        detail={"reason_code": result.get("reason_code")},
    )
    return result
