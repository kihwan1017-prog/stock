from __future__ import annotations

from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.trading.account_service import (
    PaperAccountError,
)
from stock_platform.trading.execution_service import (
    PaperExecutionService,
)
from stock_platform.trading.paper_engine import (
    PaperOrderValidationError,
)


router = APIRouter(
    prefix="/api/v1/paper-executions",
    tags=["Paper Executions"],
)


class ApplyOrderFillRequest(BaseModel):
    account_id: int = Field(gt=0)
    order_id: int = Field(gt=0)
    fill_quantity: Decimal = Field(gt=0)
    fill_price: Decimal = Field(gt=0)


@router.post("/fills")
def apply_order_fill(
    request: ApplyOrderFillRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return PaperExecutionService(
            session
        ).apply_fill(
            account_id=request.account_id,
            order_id=request.order_id,
            fill_quantity=request.fill_quantity,
            fill_price=request.fill_price,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (
        ValueError,
        PaperOrderValidationError,
        PaperAccountError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
