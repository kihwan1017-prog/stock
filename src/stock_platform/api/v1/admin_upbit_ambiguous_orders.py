"""STEP 8-5-12 — Admin Upbit Ambiguous Order API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.broker.upbit.ambiguous_resolution_service import (
    UpbitAmbiguousOrderResolutionService,
)
from stock_platform.broker.upbit.ambiguous_resolver import (
    UpbitAmbiguousOrderResolver,
)


admin_router = APIRouter(
    prefix="/api/v1/admin/upbit/ambiguous-orders",
    tags=["Admin Upbit Ambiguous Orders"],
    dependencies=[Depends(require_admin)],
)


def _order_dict(row) -> dict:
    return {
        "order_id": int(row.order_id),
        "client_order_id": row.client_order_id,
        "client_order_identifier": row.client_order_identifier,
        "broker_order_id": row.broker_order_id,
        "user_broker_account_id": row.user_broker_account_id,
        "symbol": row.symbol,
        "side_code": row.side_code,
        "order_type_code": row.order_type_code,
        "order_price": (
            str(row.order_price) if row.order_price is not None else None
        ),
        "order_quantity": str(row.order_quantity),
        "status_code": row.status_code,
        "submission_generation": int(
            getattr(row, "submission_generation", 1) or 1
        ),
        "ambiguous_since": (
            row.ambiguous_since.isoformat()
            if getattr(row, "ambiguous_since", None)
            else None
        ),
        "ambiguity_reason": getattr(row, "ambiguity_reason", None),
        "remote_lookup_status": getattr(
            row, "remote_lookup_status", None
        ),
        "remote_lookup_attempt_count": int(
            getattr(row, "remote_lookup_attempt_count", 0) or 0
        ),
        "last_remote_lookup_at": (
            row.last_remote_lookup_at.isoformat()
            if getattr(row, "last_remote_lookup_at", None)
            else None
        ),
        "next_remote_lookup_at": (
            row.next_remote_lookup_at.isoformat()
            if getattr(row, "next_remote_lookup_at", None)
            else None
        ),
        "source_signal_id": getattr(row, "source_signal_id", None),
        "order_fingerprint": getattr(row, "order_fingerprint", None),
        # STEP 8-5-14 — Resolver Scheduler Claim 상태 (ADMIN 전용 가시성)
        "resolver_claimed_by": getattr(row, "resolver_claimed_by", None),
        "resolver_claimed_at": (
            row.resolver_claimed_at.isoformat()
            if getattr(row, "resolver_claimed_at", None)
            else None
        ),
        "resolver_claim_expires_at": (
            row.resolver_claim_expires_at.isoformat()
            if getattr(row, "resolver_claim_expires_at", None)
            else None
        ),
    }


class ReasonBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@admin_router.get("")
def list_ambiguous_orders(
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    rows = UpbitAmbiguousOrderResolver(session).list_ambiguous(
        limit=limit
    )
    return {"items": [_order_dict(r) for r in rows], "count": len(rows)}


@admin_router.get("/health")
def ambiguous_health(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    return UpbitAmbiguousOrderResolver(session).health_summary()


@admin_router.get("/{order_id}")
def get_ambiguous_order(
    order_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    from stock_platform.order.repository import TradingOrderRepository

    row = TradingOrderRepository(session).get(order_id)
    if row is None or (row.broker_code or "").upper() != "UPBIT":
        raise HTTPException(404, detail="Order not found")
    return _order_dict(row)


@admin_router.post("/{order_id}/lookup")
def lookup_ambiguous_order(
    order_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    out = UpbitAmbiguousOrderResolver(session).resolve_one(
        order_id, actor=user.username, force=True
    )
    audit.record(
        event_type="ADMIN_UPBIT_AMBIGUOUS_LOOKUP",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={"order_id": order_id, "status": out.get("status")},
    )
    session.commit()
    return out


@admin_router.post("/{order_id}/mark-manual-review")
def mark_manual_review(
    order_id: int,
    body: ReasonBody,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    from stock_platform.order.repository import TradingOrderRepository

    order = TradingOrderRepository(session).get(order_id)
    if order is None:
        raise HTTPException(404, detail="Order not found")
    out = UpbitAmbiguousOrderResolver(session)._to_manual_review(
        order, reason=body.reason, actor=user.username
    )
    session.commit()
    return out


@admin_router.post("/{order_id}/approve-resubmit")
def approve_resubmit(
    order_id: int,
    body: ReasonBody,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    out = UpbitAmbiguousOrderResolver(session).approve_resubmit(
        order_id, actor=user.username, reason=body.reason
    )
    if out.get("status") in {"NOT_FOUND", "INVALID_STATE", "MARKET_ORDER_STALE"}:
        raise HTTPException(400, detail=out)
    audit.record(
        event_type="ADMIN_UPBIT_RESUBMIT_APPROVED",
        actor=user.username,
        detail={"order_id": order_id, "status": out.get("status")},
    )
    session.commit()
    return out


@admin_router.post("/{order_id}/retry-lookup")
def retry_lookup_via_scheduler_path(
    order_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    """STEP 8-5-14 — Scheduler와 동일한 Claim 경로로 즉시 1건 조회.

    /lookup 과 달리 DB Claim 을 실제로 걸고 해제하므로 Scheduler가
    동시에 동일 주문을 처리하는 경합을 방지한다.
    """

    from stock_platform.order.repository import TradingOrderRepository

    order = TradingOrderRepository(session).get(order_id)
    if order is None or (order.broker_code or "").upper() != "UPBIT":
        raise HTTPException(404, detail="Order not found")

    service = UpbitAmbiguousOrderResolutionService(session)
    claimed = service._try_claim(
        order_id,
        run_token=f"admin:{user.user_id}",
        claim_seconds=60,
    )
    if not claimed:
        raise HTTPException(
            409,
            detail=(
                "이미 Scheduler 또는 다른 요청이 Claim 중입니다. "
                "잠시 후 다시 시도하세요."
            ),
        )
    try:
        out = UpbitAmbiguousOrderResolver(session).resolve_one(
            order_id, actor=f"admin:{user.user_id}", force=True
        )
    finally:
        service._release_claim(order_id, commit=False)
        session.commit()

    audit.record(
        event_type="ADMIN_UPBIT_AMBIGUOUS_RETRY_LOOKUP",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={"order_id": order_id, "status": out.get("status")},
    )
    session.commit()
    return out


@admin_router.post("/{order_id}/release-stale-claim")
def release_stale_claim(
    order_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    """만료된(Expire 지난) Claim만 강제 해제 — 유효 Claim은 거부."""

    out = UpbitAmbiguousOrderResolutionService(session).release_stale_claim(
        order_id, actor=f"admin:{user.user_id}"
    )
    if out.get("status") != "RELEASED":
        raise HTTPException(409, detail=out)
    audit.record(
        event_type="ADMIN_UPBIT_AMBIGUOUS_RELEASE_STALE_CLAIM",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={"order_id": order_id},
    )
    session.commit()
    return out


@admin_router.post("/{order_id}/reject-resubmit")
def reject_resubmit(
    order_id: int,
    body: ReasonBody,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    out = UpbitAmbiguousOrderResolver(session).reject_resubmit(
        order_id, actor=user.username, reason=body.reason
    )
    if out.get("status") == "NOT_FOUND":
        raise HTTPException(404, detail="Order not found")
    session.commit()
    return out
