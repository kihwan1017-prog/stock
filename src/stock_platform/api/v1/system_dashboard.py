from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.operation.operations_dashboard_service import (
    OperationsDashboardService,
)


router = APIRouter(
    prefix="/api/v1/system/dashboard",
    tags=["System Dashboard"],
)


@router.get("")
async def get_system_dashboard(
    account_id: int = Query(default=1, gt=0),
    exchange_code: str = Query(default="KRX"),
    recent_limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return await OperationsDashboardService(
            session
        ).build(
            account_id=account_id,
            exchange_code=exchange_code,
            recent_limit=recent_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
