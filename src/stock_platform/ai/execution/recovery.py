"""STEP 11-5 — Startup Recovery (자동 외부 재호출 금지)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.execution.constants import RequestStatus
from stock_platform.ai.execution.entities import AIExecutionRequestEntity
from stock_platform.ai.execution.service import AIExecutionService


def recover_stale_executions(session: Session, *, actor: str = "STARTUP") -> dict[str, Any]:
    """QUEUED/RUNNING/CANCEL_REQUESTED lease 만료 처리.

    - 만료 RUNNING → ABANDONED (자동 외부 재호출 금지)
    - 만료 QUEUED → ABANDONED (자동 재큐잉도 기본 금지 — 운영자 검토)
    - CANCEL_REQUESTED → CANCELLED
    """

    svc = AIExecutionService(session)
    now = datetime.now(timezone.utc)
    rows = list(
        session.scalars(
            select(AIExecutionRequestEntity).where(
                AIExecutionRequestEntity.status.in_(
                    [
                        RequestStatus.QUEUED.value,
                        RequestStatus.RUNNING.value,
                        RequestStatus.CANCEL_REQUESTED.value,
                    ]
                )
            )
        )
    )
    abandoned = 0
    cancelled = 0
    for row in rows:
        lease_expired = (
            row.lease_expires_at is None or row.lease_expires_at <= now
        )
        if row.status == RequestStatus.CANCEL_REQUESTED.value:
            prev = row.status
            row.status = RequestStatus.CANCELLED.value
            row.cancelled_at = now
            row.completed_at = now
            row.lease_owner = None
            row.lease_expires_at = None
            svc._event(
                row.execution_request_id,
                event_type="AI_EXECUTION_CANCELLED",
                actor=actor,
                previous=prev,
                new=row.status,
                detail={"recovery": True},
                correlation_id=row.correlation_id,
            )
            cancelled += 1
            continue
        if not lease_expired and row.lease_owner:
            continue
        prev = row.status
        row.status = RequestStatus.ABANDONED.value
        row.completed_at = now
        row.sanitized_error = "startup_recovery_abandoned"
        row.lease_owner = None
        row.lease_expires_at = None
        svc._event(
            row.execution_request_id,
            event_type="AI_EXECUTION_ABANDONED",
            actor=actor,
            previous=prev,
            new=row.status,
            detail={
                "recovery": True,
                "auto_external_retry": False,
                "review_required": True,
            },
            correlation_id=row.correlation_id,
        )
        svc._event(
            row.execution_request_id,
            event_type="AI_EXECUTION_RECOVERY_REVIEW_REQUIRED",
            actor=actor,
            previous=prev,
            new=row.status,
            detail={"request_id": row.execution_request_id},
            correlation_id=row.correlation_id,
        )
        abandoned += 1
    session.commit()
    return {
        "abandoned": abandoned,
        "cancelled": cancelled,
        "auto_external_retry": 0,
    }
