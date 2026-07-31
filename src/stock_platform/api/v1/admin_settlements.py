"""STEP 8-5-16 — Admin Account Settlement API."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session
from stock_platform.settlement.constants import SettlementType
from stock_platform.settlement.entities import (
    AccountDailySettlementEntity,
    AccountDailySettlementIssueEntity,
)
from stock_platform.settlement.service import AccountDailySettlementService

admin_router = APIRouter(
    prefix="/api/v1/admin/settlements",
    tags=["Admin Settlements"],
    dependencies=[Depends(require_admin)],
)


def _settlement_dict(row: AccountDailySettlementEntity) -> dict:
    return {
        "settlement_id": int(row.settlement_id),
        "user_broker_account_id": row.user_broker_account_id,
        "paper_account_id": row.paper_account_id,
        "broker_code": row.broker_code,
        "market_date": row.market_date.isoformat(),
        "calendar_revision": row.calendar_revision,
        "settlement_type": row.settlement_type,
        "status_code": row.status_code,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": (
            row.completed_at.isoformat() if row.completed_at else None
        ),
        "open_order_count": int(row.open_order_count or 0),
        "unresolved_order_count": int(row.unresolved_order_count or 0),
        "position_mismatch_count": int(row.position_mismatch_count or 0),
        "cash_mismatch_amount": str(row.cash_mismatch_amount or 0),
        "realized_pnl": str(row.realized_pnl or 0),
        "unrealized_pnl": str(row.unrealized_pnl or 0),
        "fees": str(row.fees or 0),
        "taxes": str(row.taxes or 0),
        "net_pnl": str(row.net_pnl or 0),
        "opening_equity": (
            str(row.opening_equity) if row.opening_equity is not None else None
        ),
        "closing_equity": (
            str(row.closing_equity) if row.closing_equity is not None else None
        ),
        "internal_equity": (
            str(row.internal_equity)
            if row.internal_equity is not None
            else None
        ),
        "external_equity": (
            str(row.external_equity)
            if row.external_equity is not None
            else None
        ),
        "equity_difference": (
            str(row.equity_difference)
            if row.equity_difference is not None
            else None
        ),
        "result_code": row.result_code,
        "result_summary": row.result_summary,
        "external_snapshot_meta": row.external_snapshot_meta or {},
    }


def _issue_dict(row: AccountDailySettlementIssueEntity) -> dict:
    return {
        "issue_id": int(row.issue_id),
        "settlement_id": int(row.settlement_id),
        "issue_type": row.issue_type,
        "severity": row.severity,
        "symbol": row.symbol,
        "local_value": row.local_value,
        "external_value": row.external_value,
        "difference": row.difference,
        "tolerance": row.tolerance,
        "description": row.description,
        "resolved": bool(row.resolved),
        "resolved_by": row.resolved_by,
        "resolved_at": (
            row.resolved_at.isoformat() if row.resolved_at else None
        ),
        "resolution_note": row.resolution_note,
    }


class ReasonBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ResolveIssueBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    note: str = Field(min_length=1, max_length=1000)


class RunSettlementBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    market_date: date


def _actor(admin: AuthenticatedUser) -> str:
    return admin_actor_label(admin)


@admin_router.get("")
def list_settlements(
    market_date: date | None = None,
    status_code: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    rows = AccountDailySettlementService(session).list_settlements(
        market_date=market_date,
        status_code=status_code,
        limit=limit,
    )
    return {
        "items": [_settlement_dict(r) for r in rows],
        "count": len(rows),
    }


@admin_router.get("/health")
def settlement_health(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    return AccountDailySettlementService(session).health_summary()


@admin_router.get("/accounts/{uba_id}/settlements")
def list_uba_settlements(
    uba_id: int,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    rows = list(
        session.scalars(
            select(AccountDailySettlementEntity)
            .where(
                AccountDailySettlementEntity.user_broker_account_id
                == int(uba_id)
            )
            .order_by(AccountDailySettlementEntity.market_date.desc())
            .limit(limit)
        )
    )
    return {"items": [_settlement_dict(r) for r in rows], "count": len(rows)}


@admin_router.post("/accounts/{uba_id}/settlements/run")
def run_uba_settlement(
    uba_id: int,
    body: RunSettlementBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    from stock_platform.trading.account_models import UserBrokerAccount

    uba = session.get(UserBrokerAccount, int(uba_id))
    if uba is None:
        raise HTTPException(status_code=404, detail="uba not found")
    stype = (
        SettlementType.UPBIT_DAILY.value
        if uba.broker_code.upper() == "UPBIT"
        else SettlementType.KRX_EOD.value
    )
    out = AccountDailySettlementService(session).settle_uba(
        user_broker_account_id=int(uba_id),
        broker_code=uba.broker_code,
        market_date=body.market_date,
        settlement_type=stype,
        actor=_actor(admin),
    )
    session.commit()
    audit.record(
        event_type="ADMIN_SETTLEMENT_RUN",
        actor=_actor(admin),
        detail={
            "uba_id": uba_id,
            "reason": body.reason[:200],
            "market_date": body.market_date.isoformat(),
        },
    )
    return _settlement_dict(out)


@admin_router.post("/paper-accounts/{paper_id}/settlements/run")
def run_paper_settlement(
    paper_id: int,
    body: RunSettlementBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    # STEP 2-5-3 — FK 위반(500)이 아니라 명확한 404로 응답하기 위한 최소
    # 존재 검증. run_uba_settlement와 동일 패턴. Soft-deleted 계좌도
    # 관리자 지연/복구 정산 목적상 계속 허용한다(운영자 전용 override).
    from stock_platform.trading.account_models import PaperAccount

    paper = session.get(PaperAccount, int(paper_id))
    if paper is None:
        raise HTTPException(status_code=404, detail="paper account not found")
    out = AccountDailySettlementService(session).settle_paper_account(
        paper_account_id=int(paper_id),
        market_date=body.market_date,
        settlement_type=SettlementType.PAPER_STOCK_EOD.value,
        actor=_actor(admin),
    )
    session.commit()
    audit.record(
        event_type="ADMIN_PAPER_SETTLEMENT_RUN",
        actor=_actor(admin),
        detail={
            "paper_id": paper_id,
            "reason": body.reason[:200],
            "market_date": body.market_date.isoformat(),
        },
    )
    return _settlement_dict(out)


@admin_router.get("/{settlement_id}")
def get_settlement(
    settlement_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    row = session.get(AccountDailySettlementEntity, int(settlement_id))
    if row is None:
        raise HTTPException(status_code=404, detail="settlement not found")
    return _settlement_dict(row)


@admin_router.get("/{settlement_id}/issues")
def list_issues(
    settlement_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    rows = list(
        session.scalars(
            select(AccountDailySettlementIssueEntity).where(
                AccountDailySettlementIssueEntity.settlement_id
                == int(settlement_id)
            )
        )
    )
    return {"items": [_issue_dict(r) for r in rows], "count": len(rows)}


def _rerun_settlement(
    *,
    settlement_id: int,
    reason: str,
    session: Session,
    admin: AuthenticatedUser,
    audit: AuditLogService,
    event_type: str,
) -> dict:
    row = session.get(AccountDailySettlementEntity, int(settlement_id))
    if row is None:
        raise HTTPException(status_code=404, detail="settlement not found")
    svc = AccountDailySettlementService(session)
    actor = _actor(admin)
    if row.paper_account_id is not None:
        out = svc.settle_paper_account(
            paper_account_id=int(row.paper_account_id),
            market_date=row.market_date,
            settlement_type=row.settlement_type,
            calendar_revision=row.calendar_revision,
            actor=actor,
        )
    elif row.user_broker_account_id is not None:
        out = svc.settle_uba(
            user_broker_account_id=int(row.user_broker_account_id),
            broker_code=row.broker_code,
            market_date=row.market_date,
            settlement_type=row.settlement_type,
            calendar_revision=row.calendar_revision,
            actor=actor,
        )
    else:
        raise HTTPException(status_code=400, detail="invalid settlement")
    session.commit()
    audit.record(
        event_type=event_type,
        actor=actor,
        detail={
            "settlement_id": settlement_id,
            "reason": reason[:200],
        },
    )
    return _settlement_dict(out)


@admin_router.post("/{settlement_id}/retry")
def retry_settlement(
    settlement_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    return _rerun_settlement(
        settlement_id=settlement_id,
        reason=body.reason,
        session=session,
        admin=admin,
        audit=audit,
        event_type="ADMIN_SETTLEMENT_RETRY",
    )


@admin_router.post("/{settlement_id}/reconcile")
def reconcile_settlement(
    settlement_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    return _rerun_settlement(
        settlement_id=settlement_id,
        reason=body.reason,
        session=session,
        admin=admin,
        audit=audit,
        event_type="ADMIN_SETTLEMENT_RECONCILE",
    )


@admin_router.post("/{settlement_id}/issues/{issue_id}/resolve")
def resolve_issue(
    settlement_id: int,
    issue_id: int,
    body: ResolveIssueBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    issue = session.get(AccountDailySettlementIssueEntity, int(issue_id))
    if issue is None or int(issue.settlement_id) != int(settlement_id):
        raise HTTPException(status_code=404, detail="issue not found")
    out = AccountDailySettlementService(session).resolve_issue(
        issue_id=int(issue_id),
        resolved_by=str(getattr(admin, "username", admin.user_id)),
        note=f"{body.reason}: {body.note}",
    )
    session.commit()
    audit.record(
        event_type="ADMIN_SETTLEMENT_ISSUE_RESOLVE",
        actor=_actor(admin),
        detail={"issue_id": issue_id, "reason": body.reason[:200]},
    )
    return _issue_dict(out)
