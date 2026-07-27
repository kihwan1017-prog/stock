"""STEP 8-5-17 — USER Snapshot 상태 (내부 ID/Hash/Generation 미노출)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.auth.deps import AuthenticatedUser, get_current_user
from stock_platform.broker.account_models import BrokerAccountSnapshotEntity
from stock_platform.broker.snapshot_constants import BrokerSnapshotStatus
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session
from stock_platform.trading.account_models import UserBrokerAccount

user_router = APIRouter(
    prefix="/api/v1/user/broker-snapshots",
    tags=["User Broker Snapshots"],
)


def _status_label(row: BrokerAccountSnapshotEntity) -> str:
    settings = get_settings()
    max_age = int(settings.settlement_price_max_age_seconds)
    if row.snapshot_status != BrokerSnapshotStatus.ACTIVE.value:
        return "오래됨"
    t = row.snapshot_time or row.synchronized_at
    if t is None:
        return "오래됨"
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - t).total_seconds()
    if age > max_age:
        return "오래됨"
    if age > max_age * 0.7:
        return "동기화 중"
    return "Snapshot 정상"


@user_router.get("")
def list_my_snapshot_status(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    uba_ids = list(
        session.scalars(
            select(UserBrokerAccount.user_broker_account_id).where(
                UserBrokerAccount.user_id == int(user.user_id)
            )
        )
    )
    if not uba_ids:
        return {"items": [], "count": 0}
    rows = list(
        session.scalars(
            select(BrokerAccountSnapshotEntity).where(
                BrokerAccountSnapshotEntity.user_broker_account_id.in_(
                    uba_ids
                ),
                BrokerAccountSnapshotEntity.snapshot_status
                == BrokerSnapshotStatus.ACTIVE.value,
            )
        )
    )
    items = [
        {
            "broker_code": r.broker_code,
            "status_label": _status_label(r),
            "is_fresh": _status_label(r) == "Snapshot 정상",
        }
        for r in rows
    ]
    return {"items": items, "count": len(items)}


@user_router.get("/accounts/{uba_id}")
def get_my_uba_snapshot_status(
    uba_id: int,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    uba = session.get(UserBrokerAccount, int(uba_id))
    if uba is None or int(uba.user_id) != int(user.user_id):
        raise HTTPException(status_code=404, detail="account not found")
    row = session.scalar(
        select(BrokerAccountSnapshotEntity).where(
            BrokerAccountSnapshotEntity.user_broker_account_id
            == int(uba_id),
            BrokerAccountSnapshotEntity.snapshot_status
            == BrokerSnapshotStatus.ACTIVE.value,
        )
    )
    if row is None:
        return {
            "broker_code": uba.broker_code,
            "status_label": "동기화 중",
            "is_fresh": False,
        }
    label = _status_label(row)
    return {
        "broker_code": row.broker_code,
        "status_label": label,
        "is_fresh": label == "Snapshot 정상",
    }
