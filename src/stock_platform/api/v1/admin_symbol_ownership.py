"""Admin Symbol Ownership — READ list + exclusion toggle (주문 없음)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import AuthenticatedUser, require_admin
from stock_platform.database.session import get_db_session
from stock_platform.trading.symbol_ownership import SymbolOwnershipService

router = APIRouter(
    prefix="/api/v1/admin/symbol-ownership",
    tags=["Admin Symbol Ownership"],
)


class ExclusionBody(BaseModel):
    user_broker_account_id: int
    broker_code: str = Field(min_length=2, max_length=30)
    symbol: str = Field(min_length=1, max_length=40)
    enabled: bool = True
    reason: str | None = None


@router.get("/{uba_id}")
def list_ownership(
    uba_id: int,
    broker_code: str = Query(default="UPBIT"),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    rows = SymbolOwnershipService(session).list_account_symbols(
        broker_code=broker_code,
        user_broker_account_id=uba_id,
    )
    return {
        "user_broker_account_id": uba_id,
        "broker_code": broker_code.upper(),
        "items": [r.to_dict() for r in rows],
        "total": len(rows),
    }


@router.get("/{uba_id}/{symbol}")
def get_ownership(
    uba_id: int,
    symbol: str,
    broker_code: str = Query(default="UPBIT"),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    result = SymbolOwnershipService(session).resolve(
        broker_code=broker_code,
        user_broker_account_id=uba_id,
        symbol=symbol,
    )
    return result.to_dict()


@router.post("/exclusion")
def set_exclusion(
    body: ExclusionBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    row = SymbolOwnershipService(session).set_user_exclusion(
        user_broker_account_id=body.user_broker_account_id,
        broker_code=body.broker_code,
        symbol=body.symbol,
        enabled=body.enabled,
        reason=body.reason,
        created_by=f"admin:{user.username}",
    )
    session.commit()
    return {
        "ok": True,
        "symbol": row.symbol,
        "enabled": bool(row.enabled),
        "broker_code": row.broker_code,
        "user_broker_account_id": int(row.user_broker_account_id),
    }
