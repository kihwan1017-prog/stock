from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from stock_platform.api.deps_admin import require_admin
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.risk_engine.account_state_service import (
    RiskAccountStateService,
)


router = APIRouter(
    prefix="/api/v1/realtime-risk/account-state",
    tags=["Realtime Risk Account"],
    dependencies=[Depends(require_admin)],
)


@router.get("/by-uba/{user_broker_account_id}")
def get_risk_account_state_by_uba(
    user_broker_account_id: int,
    exchange_code: str = Query(...),
    symbol: str = Query(...),
    session: Session = Depends(get_db_session),
):
    """STEP 8-5-18 — UBA 기준 Risk Account State."""

    try:
        return RiskAccountStateService(session).load_by_uba(
            user_broker_account_id=int(user_broker_account_id),
            exchange_code=exchange_code,
            symbol=symbol,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/{account_number}/{exchange_code}/{symbol}")
def get_risk_account_state(
    account_number: str,
    exchange_code: str,
    symbol: str,
    session: Session = Depends(get_db_session),
):
    """Gone — account_number-only 경로 제거."""

    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "LEGACY_ACCOUNT_NUMBER_ONLY",
            "message": (
                "Use /by-uba/{user_broker_account_id}"
                "?exchange_code=&symbol="
            ),
        },
    )
