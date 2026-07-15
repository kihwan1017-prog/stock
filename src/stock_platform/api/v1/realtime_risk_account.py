from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.risk_engine.account_state_service import (
    RiskAccountStateService,
)


router = APIRouter(
    prefix="/api/v1/realtime-risk/account-state",
    tags=["Realtime Risk Account"],
)


@router.get(
    "/{account_number}/{exchange_code}/{symbol}"
)
def get_risk_account_state(
    account_number: str,
    exchange_code: str,
    symbol: str,
    session: Session = Depends(get_db_session),
):
    try:
        return RiskAccountStateService(session).load(
            broker_code="KIWOOM",
            account_number=account_number,
            exchange_code=exchange_code,
            symbol=symbol,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
