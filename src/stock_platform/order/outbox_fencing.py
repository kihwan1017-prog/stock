"""Outbox fencing helpers — claim 토큰·intent·stale 응답 거부."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.order.outbox_models import OutboxStatus


class OutboxFencingError(PermissionError):
    """Fencing Token / Lease 불일치 — Broker 호출 금지."""


class OutboxAmbiguousError(RuntimeError):
    """전송 여부 불명 — 자동 재전송 금지."""


def stable_request_hash(payload: dict[str, Any]) -> str:
    """동일 주문 재시도 시 동일 Hash (키 정렬 JSON)."""

    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_outbox_audit(
    session: Session,
    *,
    event_type: str,
    detail: dict[str, Any],
    actor: str = "OUTBOX_WORKER",
) -> None:
    try:
        from stock_platform.api.deps_admin import AuditLogService

        # Secret/계좌 원문 키 제거
        safe = {
            k: v
            for k, v in detail.items()
            if k.lower()
            not in {
                "password",
                "token",
                "secret",
                "account_number",
                "payload_json",
                "access_key",
                "secret_key",
                "api_key",
                "api_secret",
                "arm_token",
            }
        }
        AuditLogService(session).record(
            event_type=event_type,
            actor=actor,
            detail=safe,
        )
    except Exception:  # noqa: BLE001
        pass


def assert_fencing_allows_mutation(
    entity: OrderOutbox,
    *,
    expected_token: int,
    worker_id: str,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(timezone.utc)
    if int(entity.fencing_token or 0) != int(expected_token):
        raise OutboxFencingError(
            f"OUTBOX_FENCING_REJECTED token "
            f"{expected_token}!={entity.fencing_token}"
        )
    if (entity.locked_by or "") != worker_id:
        raise OutboxFencingError(
            f"OUTBOX_FENCING_REJECTED owner "
            f"{worker_id!r}!={entity.locked_by!r}"
        )
    if entity.lease_expires_at is not None:
        exp = entity.lease_expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= current:
            raise OutboxFencingError("OUTBOX_LEASE_EXPIRED")
    if entity.status_code in {
        OutboxStatus.DONE.value,
        OutboxStatus.FAILED.value,
        OutboxStatus.AMBIGUOUS.value,
        OutboxStatus.MANUAL_REVIEW.value,
    }:
        raise OutboxFencingError(
            f"OUTBOX_TERMINAL_STATUS:{entity.status_code}"
        )


def default_lease_ttl() -> timedelta:
    return timedelta(minutes=2)
