"""STEP 8-5-16 — USER 본인 계좌 Settlement 조회 API."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from stock_platform.auth.deps import AuthenticatedUser, get_current_user
from stock_platform.database.session import get_db_session
from stock_platform.settlement.entities import AccountDailySettlementEntity
from stock_platform.trading.account_models import (
    PaperAccount,
    UserBrokerAccount,
)

user_router = APIRouter(
    prefix="/api/v1/user/settlements",
    tags=["User Settlements"],
)


def _user_safe_dict(row: AccountDailySettlementEntity) -> dict:
    """USER 노출 — Lock/Fencing/Broker 원문/내부 stack 제외."""

    needs_review = row.status_code in {
        "MANUAL_REVIEW_REQUIRED",
        "FAILED",
        "RETRY_PENDING",
    }
    has_mismatch = (
        int(row.position_mismatch_count or 0) > 0
        or abs(float(row.cash_mismatch_amount or 0)) > 0
        or int(row.unresolved_order_count or 0) > 0
    )
    status_label = {
        "SUCCEEDED": "오늘 정산 완료",
        "SUCCEEDED_WITH_WARNINGS": "오늘 정산 완료",
        "RUNNING": "정산 진행 중",
        "PENDING": "정산 진행 중",
        "RETRY_PENDING": "계좌 정보 재확인 중",
        "MANUAL_REVIEW_REQUIRED": "정산 확인 필요",
        "FAILED": "정산 확인 필요",
        "SKIPPED": "정산 보류",
        "SUPERSEDED": "정산 보류",
    }.get(row.status_code, row.status_code)

    return {
        "settlement_id": int(row.settlement_id),
        "market_date": row.market_date.isoformat(),
        "broker_code": row.broker_code,
        "settlement_type": row.settlement_type,
        "status_code": row.status_code,
        "status_label": status_label,
        "needs_manual_review": needs_review,
        "has_mismatch": has_mismatch,
        "realized_pnl": str(row.realized_pnl or 0),
        "unrealized_pnl": str(row.unrealized_pnl or 0),
        "fees": str(row.fees or 0),
        "taxes": str(row.taxes or 0),
        "net_pnl": str(row.net_pnl or 0),
        "closing_equity": (
            str(row.closing_equity) if row.closing_equity is not None else None
        ),
        "completed_at": (
            row.completed_at.isoformat() if row.completed_at else None
        ),
    }


def _owned_account_filters(user_id: int, session: Session):
    paper_ids = list(
        session.scalars(
            select(PaperAccount.account_id).where(
                PaperAccount.user_id == int(user_id)
            )
        )
    )
    uba_ids = list(
        session.scalars(
            select(UserBrokerAccount.user_broker_account_id).where(
                UserBrokerAccount.user_id == int(user_id)
            )
        )
    )
    return paper_ids, uba_ids


@user_router.get("")
def list_my_settlements(
    market_date: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    paper_ids, uba_ids = _owned_account_filters(int(user.user_id), session)
    if not paper_ids and not uba_ids:
        return {"items": [], "count": 0}

    clauses = []
    if paper_ids:
        clauses.append(
            AccountDailySettlementEntity.paper_account_id.in_(paper_ids)
        )
    if uba_ids:
        clauses.append(
            AccountDailySettlementEntity.user_broker_account_id.in_(uba_ids)
        )
    stmt = (
        select(AccountDailySettlementEntity)
        .where(or_(*clauses))
        .order_by(
            AccountDailySettlementEntity.market_date.desc(),
            AccountDailySettlementEntity.settlement_id.desc(),
        )
        .limit(limit)
    )
    if market_date is not None:
        stmt = stmt.where(
            AccountDailySettlementEntity.market_date == market_date
        )
    rows = list(session.scalars(stmt))
    return {"items": [_user_safe_dict(r) for r in rows], "count": len(rows)}


@user_router.get("/{settlement_id}")
def get_my_settlement(
    settlement_id: int,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    row = session.get(AccountDailySettlementEntity, int(settlement_id))
    if row is None:
        raise HTTPException(status_code=404, detail="settlement not found")
    paper_ids, uba_ids = _owned_account_filters(int(user.user_id), session)
    owned = False
    if row.paper_account_id is not None and int(row.paper_account_id) in {
        int(x) for x in paper_ids
    }:
        owned = True
    if row.user_broker_account_id is not None and int(
        row.user_broker_account_id
    ) in {int(x) for x in uba_ids}:
        owned = True
    if not owned:
        raise HTTPException(status_code=404, detail="settlement not found")
    return _user_safe_dict(row)
