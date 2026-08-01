"""USER 계좌별 전략 성과 API (백테스트와 분리, IDOR 차단)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.auth.account_ownership import (
    assert_broker_account_access,
    assert_paper_account_access,
)
from stock_platform.auth.deps import AuthenticatedUser, require_permission
from stock_platform.database.session import get_db_session
from stock_platform.trading.account_strategy_performance_service import (
    AccountStrategyPerformanceService,
)
from stock_platform.trading.order_strategy_provenance import UNATTRIBUTED


router = APIRouter(
    prefix="/api/v1/user/accounts",
    tags=["User Account Strategy Performance"],
)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid datetime: {value}",
        ) from exc


@router.get("/{account_id}/strategy-performance")
def list_account_strategy_performance(
    account_id: int,
    account_type: str = Query(default="PAPER"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    kind = (account_type or "PAPER").upper()
    svc = AccountStrategyPerformanceService(session)
    start = _parse_dt(date_from)
    end = _parse_dt(date_to)
    if kind == "PAPER":
        assert_paper_account_access(user, account_id, session)
        items = svc.summarize_paper(
            paper_account_id=account_id,
            date_from=start,
            date_to=end,
        )
    else:
        assert_broker_account_access(user, account_id, session)
        items = svc.summarize_live(
            user_broker_account_id=account_id,
            date_from=start,
            date_to=end,
        )
    return {
        "account_id": account_id,
        "account_type": kind,
        "source": "ACCOUNT_LEDGER_NOT_BACKTEST",
        "unattributed_label": "전략 미식별",
        "items": items,
    }


@router.get("/{account_id}/strategy-performance/{strategy_key}")
def get_account_strategy_performance(
    account_id: int,
    strategy_key: str,
    account_type: str = Query(default="PAPER"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    payload = list_account_strategy_performance(
        account_id=account_id,
        account_type=account_type,
        date_from=date_from,
        date_to=date_to,
        user=user,
        session=session,
    )
    key = strategy_key.strip().upper()
    for item in payload["items"]:
        if key in {UNATTRIBUTED, "UNATTRIBUTED", "NONE", "NULL"}:
            if item.get("strategy_id") is None:
                return {"account_id": account_id, "item": item}
        elif item.get("strategy_id") is not None and str(
            item["strategy_id"]
        ) == strategy_key:
            return {"account_id": account_id, "item": item}
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="strategy performance not found",
    )


@router.get("/{account_id}/strategy-performance/{strategy_key}/trades")
def list_account_strategy_trades(
    account_id: int,
    strategy_key: str,
    account_type: str = Query(default="PAPER"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
    session: Session = Depends(get_db_session),
):
    kind = (account_type or "PAPER").upper()
    if kind != "PAPER":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="LIVE trade ledger detail not available yet",
        )
    assert_paper_account_access(user, account_id, session)
    key = strategy_key.strip().upper()
    unattributed = key in {UNATTRIBUTED, "UNATTRIBUTED", "NONE", "NULL"}
    strategy_id = None if unattributed else int(strategy_key)
    trades = AccountStrategyPerformanceService(session).list_paper_trades(
        paper_account_id=account_id,
        strategy_id=strategy_id,
        unattributed=unattributed,
        date_from=_parse_dt(date_from),
        date_to=_parse_dt(date_to),
        limit=limit,
    )
    return {
        "account_id": account_id,
        "strategy_key": strategy_key,
        "source": "PAPER_LEDGER",
        "items": trades,
    }
