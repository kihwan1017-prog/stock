"""STEP 8-3 — USER 계좌↔전략 연결."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import AuditLogService, get_audit_service
from stock_platform.auth.account_ownership import (
    assert_broker_account_access,
    assert_paper_account_access,
)
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
)
from stock_platform.strategy_deployment.ownership import (
    StrategyDefinitionService,
    StrategyOwnershipError,
)


router = APIRouter(
    prefix="/api/v1/user/accounts",
    tags=["User Account Strategies"],
)


class LinkBody(BaseModel):
    account_broker: str = Field(default="PAPER", max_length=30)
    account_type: str | None = Field(
        default=None,
        description="PAPER | KIWOOM | UPBIT",
    )


@router.get("/{account_id}/strategies")
def list_account_strategies(
    account_id: int,
    account_type: str = Query(default="PAPER"),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    kind = (account_type or "PAPER").upper()
    if kind == "PAPER":
        assert_paper_account_access(user, account_id, session)
        stmt = select(AccountStrategyLinkEntity).where(
            AccountStrategyLinkEntity.paper_account_id == account_id,
            AccountStrategyLinkEntity.user_id == int(user.user_id),
            AccountStrategyLinkEntity.is_active.is_(True),
        )
    else:
        assert_broker_account_access(user, account_id, session)
        stmt = select(AccountStrategyLinkEntity).where(
            AccountStrategyLinkEntity.user_broker_account_id
            == account_id,
            AccountStrategyLinkEntity.user_id == int(user.user_id),
            AccountStrategyLinkEntity.is_active.is_(True),
        )
    rows = list(session.scalars(stmt))
    return {
        "items": [
            {
                "account_strategy_link_id": int(r.account_strategy_link_id),
                "strategy_id": int(r.strategy_id),
                "paper_account_id": r.paper_account_id,
                "user_broker_account_id": r.user_broker_account_id,
                "is_active": bool(r.is_active),
            }
            for r in rows
        ]
    }


@router.post("/{account_id}/strategies/{strategy_id}")
def link_strategy(
    account_id: int,
    strategy_id: int,
    body: LinkBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    kind = (body.account_type or "PAPER").upper()
    service = StrategyDefinitionService(session)
    try:
        if kind == "PAPER":
            link = service.link_to_account(
                user,
                strategy_id=strategy_id,
                paper_account_id=account_id,
                user_broker_account_id=None,
                account_broker=body.account_broker or "PAPER",
                actor=user.username,
            )
        else:
            link = service.link_to_account(
                user,
                strategy_id=strategy_id,
                paper_account_id=None,
                user_broker_account_id=account_id,
                account_broker=body.account_broker or kind,
                actor=user.username,
            )
        session.commit()
    except StrategyOwnershipError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        session.rollback()
        raise
    audit.record(
        event_type="USER_STRATEGY_ACCOUNT_LINK",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "strategy_id": strategy_id,
            "account_id": account_id,
            "account_type": kind,
            "link_id": int(link.account_strategy_link_id),
        },
    )
    session.commit()
    return {
        "account_strategy_link_id": int(link.account_strategy_link_id),
        "strategy_id": strategy_id,
        "account_id": account_id,
    }


@router.delete("/{account_id}/strategies/{strategy_id}")
def unlink_strategy(
    account_id: int,
    strategy_id: int,
    account_type: str = Query(default="PAPER"),
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    kind = (account_type or "PAPER").upper()
    service = StrategyDefinitionService(session)
    try:
        if kind == "PAPER":
            assert_paper_account_access(user, account_id, session)
            service.unlink(
                user,
                strategy_id=strategy_id,
                paper_account_id=account_id,
                user_broker_account_id=None,
            )
        else:
            assert_broker_account_access(user, account_id, session)
            service.unlink(
                user,
                strategy_id=strategy_id,
                paper_account_id=None,
                user_broker_account_id=account_id,
            )
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    return {"ok": True}
