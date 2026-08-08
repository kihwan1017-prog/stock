"""one-shot / Worker dispatch 이후 LiveValidationRun 동기화.

TradingOrder · Outbox · broker UUID 결과와 run 상태를 일치시킨다.
DB 직접 UPDATE 없이 ORM/service 경로만 사용.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.trading.live_validation_entities import (
    LiveValidationRunEntity,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    BrokerOrderStatus,
    InternalStatus,
    smoke_broker_identifier,
)


def public_run_display_status(
    *,
    internal_status: str | None,
    broker_order_status: str | None,
    broker_order_uuid: str | None = None,
) -> str:
    """사용자 화면용 상태 라벨."""

    broker = str(broker_order_status or "").upper()
    internal = str(internal_status or "").upper()
    has_uuid = bool(str(broker_order_uuid or "").strip())

    if broker == BrokerOrderStatus.OPEN.value:
        return "WAIT"
    if broker == BrokerOrderStatus.FILLED.value:
        return "FILLED"
    if broker in {
        BrokerOrderStatus.CANCELED.value,
        BrokerOrderStatus.PARTIALLY_FILLED_CANCELED.value,
    }:
        return "CANCELED"
    if internal == InternalStatus.CANCELED.value:
        # 미전송 내부 폐기 — broker=NOT_SUBMITTED 이어도 CANCELED
        return "CANCELED"
    if broker == BrokerOrderStatus.REJECTED.value or internal == (
        InternalStatus.REJECTED.value
    ):
        return "REJECTED"
    if broker == BrokerOrderStatus.PARTIALLY_FILLED.value:
        return "PARTIALLY_FILLED"
    if (
        broker
        in {
            BrokerOrderStatus.SUBMISSION_UNKNOWN.value,
            BrokerOrderStatus.UNKNOWN.value,
        }
        or internal == InternalStatus.MANUAL_REVIEW_REQUIRED.value
    ):
        return "AMBIGUOUS"
    if has_uuid and broker == BrokerOrderStatus.NOT_SUBMITTED.value:
        # 불일치 방어 — UUID 있으면 미전송으로 표시하지 않음
        return "SUBMITTED"
    if broker in {
        BrokerOrderStatus.ACCEPTED.value,
    } or internal in {
        InternalStatus.BROKER_TRACKING.value,
        InternalStatus.ORDER_SUBMITTED.value,
        InternalStatus.ORDER_ACCEPTED.value,
        InternalStatus.BROKER_SUBMISSION_PENDING.value,
    }:
        if broker != BrokerOrderStatus.NOT_SUBMITTED.value or has_uuid:
            return "SUBMITTED"
    if internal in {
        InternalStatus.QUEUED.value,
        InternalStatus.OUTBOX_PENDING.value,
        InternalStatus.OUTBOX_DISPATCHING.value,
    } and broker == BrokerOrderStatus.NOT_SUBMITTED.value:
        return "QUEUED"
    if broker == BrokerOrderStatus.NOT_SUBMITTED.value:
        return "NOT_SUBMITTED"
    return broker or internal or "UNKNOWN"


def _force_internal(
    run: LiveValidationRunEntity,
    new_status: str,
    *,
    actor: str,
) -> None:
    """tracking과 동일 — sync는 강제 전이(히스토리 기록)."""

    current = run.internal_status or run.status_code
    if current == new_status:
        run.status_code = new_status
        run.internal_status = new_status
        return
    run.internal_status = new_status
    run.status_code = new_status
    run.updated_at = datetime.now(timezone.utc)
    detail = dict(run.detail or {})
    hist = list(detail.get("transitions") or [])
    hist.append(
        {
            "from": current,
            "to": new_status,
            "actor": actor,
            "at": datetime.now(timezone.utc).isoformat(),
            "via": "dispatch_sync",
        }
    )
    detail["transitions"] = hist[-40:]
    run.detail = detail


def sync_live_validation_run_after_dispatch(
    session: Session,
    *,
    order_id: int,
    outbox_id: int,
    actor: str,
    outcome: str | None = None,
    upbit_state: str | None = None,
) -> dict[str, Any]:
    """Outbox/Order 결과를 linked smoke run에 반영 (멱등).

    upbit_state: 선택적 READ-ONLY 조회 state (wait/done/cancel).
    terminal로 임의 종결하지 않음 — wait면 BROKER_TRACKING 유지.
    """

    from sqlalchemy import select

    order = TradingOrderRepository(session).get(int(order_id))
    if order is None:
        return {"applied": False, "reason": "order_not_found"}

    meta = dict(order.metadata_payload or {})
    smoke_run_id = str(meta.get("smoke_run_id") or "").strip()
    if not smoke_run_id:
        return {"applied": False, "reason": "not_smoke_order"}

    run = session.scalar(
        select(LiveValidationRunEntity).where(
            LiveValidationRunEntity.run_id == smoke_run_id,
            LiveValidationRunEntity.order_id == int(order_id),
        )
    )
    if run is None:
        # order_id 미연결 레거시 — run_id만으로 재시도
        run = session.scalar(
            select(LiveValidationRunEntity).where(
                LiveValidationRunEntity.run_id == smoke_run_id
            )
        )
    if run is None:
        return {"applied": False, "reason": "run_not_found"}

    outbox = session.get(OrderOutbox, int(outbox_id))
    outbox_status = (
        str(outbox.status_code).upper() if outbox is not None else None
    )
    broker_id = str(order.broker_order_id or "").strip() or None
    order_status = str(order.status_code or "")
    outcome_u = str(outcome or "").upper()
    upbit_u = str(upbit_state or "").lower().strip()

    prev = {
        "status": run.status_code,
        "internal_status": run.internal_status,
        "broker_order_status": run.broker_order_status,
        "order_status": run.order_status,
        "broker_order_uuid": run.broker_order_uuid,
    }

    run.order_id = int(order_id)
    run.order_status = order_status or run.order_status
    if not run.broker_identifier:
        run.broker_identifier = smoke_broker_identifier(str(run.run_id))

    # --- AMBIGUOUS / MANUAL_REVIEW ---
    if (
        outbox_status
        in {
            OutboxStatus.AMBIGUOUS.value,
            OutboxStatus.MANUAL_REVIEW.value,
        }
        or outcome_u == "AMBIGUOUS"
    ):
        _force_internal(
            run,
            InternalStatus.MANUAL_REVIEW_REQUIRED.value,
            actor=actor,
        )
        run.broker_order_status = (
            BrokerOrderStatus.SUBMISSION_UNKNOWN.value
            if not broker_id
            else BrokerOrderStatus.UNKNOWN.value
        )
        run.manual_review_required = True
        if broker_id:
            run.broker_order_uuid = broker_id
        session.flush()
        return _result(run, prev, applied=True, path="AMBIGUOUS")

    # --- SUBMITTED / broker UUID ---
    if broker_id and outbox_status == OutboxStatus.DONE.value:
        run.broker_order_uuid = broker_id
        if run.submitted_at is None:
            run.submitted_at = datetime.now(timezone.utc)
        # wait → OPEN, done → FILLED (호출측 upbit_state), 기본 ACCEPTED
        if upbit_u == "wait":
            broker_status = BrokerOrderStatus.OPEN.value
        elif upbit_u == "done":
            broker_status = BrokerOrderStatus.FILLED.value
        elif upbit_u == "cancel":
            broker_status = BrokerOrderStatus.CANCELED.value
        else:
            broker_status = BrokerOrderStatus.ACCEPTED.value

        # 이미 terminal이면 덮지 않음
        if run.broker_order_status not in {
            BrokerOrderStatus.FILLED.value,
            BrokerOrderStatus.CANCELED.value,
            BrokerOrderStatus.PARTIALLY_FILLED_CANCELED.value,
            BrokerOrderStatus.REJECTED.value,
        }:
            run.broker_order_status = broker_status

        if broker_status == BrokerOrderStatus.FILLED.value:
            _force_internal(run, InternalStatus.FILLED.value, actor=actor)
            run.status_confirmed_at = datetime.now(timezone.utc)
        elif broker_status == BrokerOrderStatus.CANCELED.value:
            _force_internal(run, InternalStatus.CANCELED.value, actor=actor)
            run.status_confirmed_at = datetime.now(timezone.utc)
        else:
            _force_internal(
                run, InternalStatus.BROKER_TRACKING.value, actor=actor
            )
            if run.watch_deadline_at is None:
                run.watch_deadline_at = datetime.now(timezone.utc) + timedelta(
                    seconds=60
                )
            if run.next_track_at is None:
                run.next_track_at = datetime.now(timezone.utc) + timedelta(
                    seconds=1
                )
        run.manual_review_required = False
        session.flush()
        return _result(run, prev, applied=True, path="SUBMITTED")

    # --- REJECTED ---
    if order_status.upper() == "REJECTED" or outcome_u in {
        "REJECTED",
        "BROKER_REJECTED",
    }:
        _force_internal(run, InternalStatus.REJECTED.value, actor=actor)
        run.broker_order_status = BrokerOrderStatus.REJECTED.value
        session.flush()
        return _result(run, prev, applied=True, path="REJECTED")

    # --- FAILED / NOT_SUBMITTED (전송 전 실패 · retire) ---
    if (
        outbox_status == OutboxStatus.FAILED.value
        and not broker_id
    ) or outcome_u in {
        "FAILED",
        "DRY_RUN_BLOCKED",
        "SHADOW_BLOCKED",
        "CONFIRMED_NOT_SUBMITTED",
    }:
        if order_status.upper() == "CANCELLED":
            _force_internal(run, InternalStatus.CANCELED.value, actor=actor)
        else:
            _force_internal(run, InternalStatus.FAILED.value, actor=actor)
        run.broker_order_status = BrokerOrderStatus.NOT_SUBMITTED.value
        session.flush()
        return _result(run, prev, applied=True, path="NOT_SUBMITTED")

    # 아직 PENDING outbox — 동기화 불필요
    return _result(run, prev, applied=False, path="NOOP")


def _result(
    run: LiveValidationRunEntity,
    prev: dict[str, Any],
    *,
    applied: bool,
    path: str,
) -> dict[str, Any]:
    return {
        "applied": applied,
        "path": path,
        "run_id": run.run_id,
        "previous": prev,
        "status": run.status_code,
        "internal_status": run.internal_status,
        "broker_order_status": run.broker_order_status,
        "order_status": run.order_status,
        "broker_order_uuid": run.broker_order_uuid,
        "display_status": public_run_display_status(
            internal_status=run.internal_status,
            broker_order_status=run.broker_order_status,
            broker_order_uuid=run.broker_order_uuid,
        ),
    }
