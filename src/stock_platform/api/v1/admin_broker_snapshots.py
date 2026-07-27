"""STEP 8-5-17 — Admin Broker Snapshot Binding / Freshness API."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.broker.account_models import BrokerAccountSnapshotEntity
from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
)
from stock_platform.broker.snapshot_constants import BrokerSnapshotStatus
from stock_platform.broker.snapshot_freshness import (
    evaluate_snapshot_freshness,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session
from stock_platform.trading.account_masking import mask_account_number
from stock_platform.trading.account_models import UserBrokerAccount

admin_router = APIRouter(
    prefix="/api/v1/admin/broker-snapshots",
    tags=["Admin Broker Snapshots"],
    dependencies=[Depends(require_admin)],
)


def _actor(admin: AuthenticatedUser) -> str:
    return admin_actor_label(admin)


def _safe_dict(row: BrokerAccountSnapshotEntity) -> dict:
    age = None
    snap_time = row.snapshot_time or row.synchronized_at
    if snap_time is not None:
        if snap_time.tzinfo is None:
            snap_time = snap_time.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - snap_time).total_seconds()
    return {
        "broker_account_snapshot_id": int(row.broker_account_snapshot_id),
        "user_broker_account_id": row.user_broker_account_id,
        "paper_account_id": row.paper_account_id,
        "broker_code": row.broker_code,
        "masked_account_number": mask_account_number(row.account_number),
        "snapshot_status": row.snapshot_status,
        "snapshot_generation": int(row.snapshot_generation or 1),
        "snapshot_version": int(row.snapshot_version or 1),
        "snapshot_hash": row.snapshot_hash,
        "snapshot_time": (
            row.snapshot_time.isoformat() if row.snapshot_time else None
        ),
        "broker_server_time": (
            row.broker_server_time.isoformat()
            if row.broker_server_time
            else None
        ),
        "synchronized_at": (
            row.synchronized_at.isoformat() if row.synchronized_at else None
        ),
        "age_seconds": age,
        "deposit_amount": str(row.deposit_amount),
        "available_order_amount": str(row.available_order_amount),
        "total_evaluation_amount": str(row.total_evaluation_amount),
    }


class ReasonBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@admin_router.get("")
def list_snapshots(
    status_code: str | None = None,
    broker_code: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    stmt = select(BrokerAccountSnapshotEntity).order_by(
        BrokerAccountSnapshotEntity.synchronized_at.desc()
    )
    if status_code:
        stmt = stmt.where(
            BrokerAccountSnapshotEntity.snapshot_status == status_code
        )
    if broker_code:
        stmt = stmt.where(
            BrokerAccountSnapshotEntity.broker_code == broker_code.upper()
        )
    rows = list(session.scalars(stmt.limit(limit)))
    return {"items": [_safe_dict(r) for r in rows], "count": len(rows)}


@admin_router.get("/health")
def snapshot_health(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    settings = get_settings()
    max_age = int(settings.settlement_price_max_age_seconds)
    by_status = dict(
        session.execute(
            select(
                BrokerAccountSnapshotEntity.snapshot_status,
                func.count(),
            ).group_by(BrokerAccountSnapshotEntity.snapshot_status)
        ).all()
    )
    active = list(
        session.scalars(
            select(BrokerAccountSnapshotEntity).where(
                BrokerAccountSnapshotEntity.snapshot_status
                == BrokerSnapshotStatus.ACTIVE.value
            )
        )
    )
    now = datetime.now(timezone.utc)
    stale_count = 0
    ages: list[float] = []
    for row in active:
        t = row.snapshot_time or row.synchronized_at
        if t is None:
            stale_count += 1
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        age = (now - t).total_seconds()
        ages.append(age)
        if age > max_age:
            stale_count += 1
    return {
        "by_status": {str(k): int(v) for k, v in by_status.items()},
        "active_count": len(active),
        "orphan_count": int(
            by_status.get(BrokerSnapshotStatus.ORPHAN.value, 0) or 0
        ),
        "retired_count": int(
            by_status.get(BrokerSnapshotStatus.RETIRED.value, 0) or 0
        ),
        "stale_active_count": stale_count,
        "max_age_seconds": max_age,
        "max_age_among_active": max(ages) if ages else None,
        "avg_age_among_active": (
            sum(ages) / len(ages) if ages else None
        ),
        "binding_required": True,
    }


@admin_router.get("/orphans")
def list_orphan_snapshots(
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    rows = BrokerAccountSnapshotRepository(session).list_orphans(limit=limit)
    return {"items": [_safe_dict(r) for r in rows], "count": len(rows)}


class RebindBody(BaseModel):
    target_user_broker_account_id: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


@admin_router.post("/{snapshot_id}/rebind")
def rebind_orphan_snapshot(
    snapshot_id: int,
    body: RebindBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    audit.record(
        event_type="ORPHAN_SNAPSHOT_REBIND_REQUESTED",
        actor=_actor(admin),
        detail={
            "snapshot_id": snapshot_id,
            "target_uba": body.target_user_broker_account_id,
            "reason": body.reason[:200],
        },
    )
    try:
        row = BrokerAccountSnapshotRepository(session).rebind_orphan(
            snapshot_id=int(snapshot_id),
            target_user_broker_account_id=int(
                body.target_user_broker_account_id
            ),
            reason=body.reason,
            actor=_actor(admin),
        )
    except LookupError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit.record(
        event_type="ORPHAN_SNAPSHOT_REBOUND",
        actor=_actor(admin),
        detail={
            "snapshot_id": snapshot_id,
            "target_uba": body.target_user_broker_account_id,
            "reason": body.reason[:200],
        },
    )
    session.commit()
    return _safe_dict(row)


@admin_router.post("/{snapshot_id}/retire")
def retire_orphan_snapshot(
    snapshot_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        row = BrokerAccountSnapshotRepository(session).retire_orphan(
            snapshot_id=int(snapshot_id),
            reason=body.reason,
            actor=_actor(admin),
        )
    except LookupError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit.record(
        event_type="ORPHAN_SNAPSHOT_RETIRED",
        actor=_actor(admin),
        detail={
            "snapshot_id": snapshot_id,
            "reason": body.reason[:200],
        },
    )
    session.commit()
    return _safe_dict(row)


@admin_router.get("/{snapshot_id}")
def get_snapshot(
    snapshot_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    row = session.get(BrokerAccountSnapshotEntity, int(snapshot_id))
    if row is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    return _safe_dict(row)


@admin_router.post("/{snapshot_id}/verify")
def verify_snapshot(
    snapshot_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    row = session.get(BrokerAccountSnapshotEntity, int(snapshot_id))
    if row is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    if row.user_broker_account_id is None:
        raise HTTPException(
            status_code=400, detail="snapshot has no UBA binding"
        )
    freshness = evaluate_snapshot_freshness(
        snapshot=row,
        expected_uba_id=int(row.user_broker_account_id),
        expected_broker_code=row.broker_code,
        max_age_seconds=int(
            get_settings().settlement_price_max_age_seconds
        ),
    )
    audit.record(
        event_type="SNAPSHOT_VERIFY",
        actor=_actor(admin),
        detail={
            "snapshot_id": snapshot_id,
            "ok": freshness.ok,
            "reason": freshness.reason,
            "admin_reason": body.reason[:200],
        },
    )
    session.commit()
    return {
        "snapshot": _safe_dict(row),
        "freshness": {
            "ok": freshness.ok,
            "reason": freshness.reason,
            "age_seconds": freshness.age_seconds,
            "max_age_seconds": freshness.max_age_seconds,
        },
    }


# UBA 하위 경로 — 별도 prefix 라우터
uba_router = APIRouter(
    prefix="/api/v1/admin/user-broker-accounts",
    tags=["Admin Broker Snapshots"],
    dependencies=[Depends(require_admin)],
)


@uba_router.get("/{uba_id}/snapshots")
def list_uba_snapshots(
    uba_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    rows = list(
        session.scalars(
            select(BrokerAccountSnapshotEntity)
            .where(
                BrokerAccountSnapshotEntity.user_broker_account_id
                == int(uba_id)
            )
            .order_by(BrokerAccountSnapshotEntity.synchronized_at.desc())
            .limit(50)
        )
    )
    return {"items": [_safe_dict(r) for r in rows], "count": len(rows)}


@uba_router.post("/{uba_id}/refresh-snapshot")
async def refresh_uba_snapshot(
    uba_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    uba = session.get(UserBrokerAccount, int(uba_id))
    if uba is None:
        raise HTTPException(status_code=404, detail="uba not found")
    broker = str(uba.broker_code).upper()
    try:
        if broker == "UPBIT":
            from stock_platform.broker.upbit.account_factory import (
                build_upbit_private_client,
            )
            from stock_platform.broker.upbit.account_sync_service import (
                UpbitAccountSyncService,
            )

            result = await UpbitAccountSyncService(
                session=session,
                private_client=build_upbit_private_client(),
                user_broker_account_id=uba_id,
            ).synchronize(user_broker_account_id=uba_id)
        else:
            from stock_platform.broker.kiwoom.account_factory import (
                build_kiwoom_account_client,
            )
            from stock_platform.broker.kiwoom.account_sync_service import (
                KiwoomAccountSyncService,
            )

            result = await KiwoomAccountSyncService(
                session=session,
                account_client=build_kiwoom_account_client(),
                user_broker_account_id=uba_id,
            ).synchronize(user_broker_account_id=uba_id)
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        audit.record(
            event_type="SNAPSHOT_BINDING_FAILED",
            actor=_actor(admin),
            detail={
                "uba_id": uba_id,
                "error": str(exc)[:200],
                "reason": body.reason[:200],
            },
        )
        session.commit()
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from exc

    audit.record(
        event_type="SNAPSHOT_REFRESHED",
        actor=_actor(admin),
        detail={
            "uba_id": uba_id,
            "snapshot_id": result.get("broker_account_snapshot_id"),
            "reason": body.reason[:200],
        },
    )
    session.commit()
    return result


@uba_router.post("/{uba_id}/release-stale")
def release_stale(
    uba_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    count = BrokerAccountSnapshotRepository(session).release_orphan_for_uba(
        int(uba_id)
    )
    session.commit()
    audit.record(
        event_type="SNAPSHOT_STALE",
        actor=_actor(admin),
        detail={
            "uba_id": uba_id,
            "released": count,
            "reason": body.reason[:200],
        },
    )
    return {"uba_id": uba_id, "released": count}
