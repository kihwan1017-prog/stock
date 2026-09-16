from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.order.outbox_fencing import (
    OutboxFencingError,
    assert_fencing_allows_mutation,
    default_lease_ttl,
    record_outbox_audit,
    stable_request_hash,
)
from stock_platform.order.outbox_models import (
    OutboxEventType,
    OutboxStatus,
)


class OrderOutboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(
        self,
        *,
        order_id: int,
        event_type: OutboxEventType,
        idempotency_key: str,
        payload_json: dict[str, Any],
        max_retry_count: int = 5,
    ) -> OrderOutbox:
        existing = self.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing

        client_order_id = str(
            payload_json.get("client_order_id") or ""
        ).strip() or None
        broker_code = str(
            payload_json.get("broker_code") or ""
        ).strip().upper() or None
        uba_raw = payload_json.get("user_broker_account_id")
        uba_id = None if uba_raw in (None, "") else int(uba_raw)
        req_hash = stable_request_hash(payload_json)

        entity = OrderOutbox(
            order_id=order_id,
            event_type=event_type.value,
            idempotency_key=idempotency_key,
            payload_json=payload_json,
            status_code=OutboxStatus.PENDING.value,
            retry_count=0,
            max_retry_count=max_retry_count,
            fencing_token=0,
            client_order_id=client_order_id,
            broker_code=broker_code,
            user_broker_account_id=uba_id,
            request_hash=req_hash,
            correlation_id=str(
                payload_json.get("correlation_id") or ""
            ).strip()
            or None,
        )
        self._session.add(entity)
        self._session.flush()
        return entity

    def get(self, outbox_id: int) -> OrderOutbox | None:
        return self._session.get(OrderOutbox, outbox_id)

    def get_by_idempotency_key(
        self, idempotency_key: str
    ) -> OrderOutbox | None:
        return self._session.scalar(
            select(OrderOutbox).where(
                OrderOutbox.idempotency_key == idempotency_key
            )
        )

    def list_by_status(
        self, *, status: str, limit: int = 100
    ) -> list[OrderOutbox]:
        return list(
            self._session.scalars(
                select(OrderOutbox)
                .where(OrderOutbox.status_code == status.upper())
                .order_by(OrderOutbox.outbox_id.desc())
                .limit(limit)
            )
        )

    def reclaim_stale_processing(
        self,
        *,
        stale_after: timedelta,
        now: datetime | None = None,
        limit: int = 100,
    ) -> int:
        """
        Lease 만료 PROCESSING:
        - dispatch_intent 있음 → AMBIGUOUS (자동 RETRY 금지)
        - intent 없음 → RETRY 허용
        """

        current = now or datetime.now(timezone.utc)
        cutoff = current - stale_after
        stmt = (
            select(OrderOutbox)
            .where(
                OrderOutbox.status_code == OutboxStatus.PROCESSING.value,
                or_(
                    and_(
                        OrderOutbox.lease_expires_at.is_not(None),
                        OrderOutbox.lease_expires_at < current,
                    ),
                    and_(
                        OrderOutbox.lease_expires_at.is_(None),
                        OrderOutbox.locked_at.is_not(None),
                        OrderOutbox.locked_at < cutoff,
                    ),
                ),
            )
            .order_by(OrderOutbox.outbox_id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list(self._session.scalars(stmt))
        ambiguous = 0
        retried = 0
        for row in rows:
            has_intent = getattr(row, "dispatch_intent_at", None) is not None
            payload = getattr(row, "payload_json", None) or {}
            env = str(
                (payload if isinstance(payload, dict) else {}).get(
                    "environment"
                )
                or "PAPER"
            ).upper()
            if has_intent and env != "MOCK":
                row.status_code = OutboxStatus.AMBIGUOUS.value
                if hasattr(row, "ambiguous_at"):
                    row.ambiguous_at = current
                if hasattr(row, "confirmation_status"):
                    row.confirmation_status = "BROKER_CONFIRMATION_REQUIRED"
                row.locked_at = None
                row.locked_by = None
                if hasattr(row, "lease_expires_at"):
                    row.lease_expires_at = None
                row.last_error = (
                    row.last_error or "STALE_DISPATCH_AMBIGUOUS"
                )
                record_outbox_audit(
                    self._session,
                    event_type="OUTBOX_DISPATCH_AMBIGUOUS",
                    detail={
                        "outbox_id": getattr(row, "outbox_id", None),
                        "fencing_token": getattr(row, "fencing_token", None),
                        "reason": "lease_expired_after_intent",
                    },
                )
                ambiguous += 1
            else:
                row.status_code = OutboxStatus.RETRY.value
                row.next_retry_at = current
                row.locked_at = None
                row.locked_by = None
                if hasattr(row, "lease_expires_at"):
                    row.lease_expires_at = None
                if has_intent and env == "MOCK":
                    row.dispatch_intent_at = None
                    if hasattr(row, "dispatch_fencing_token"):
                        row.dispatch_fencing_token = None
                row.last_error = (
                    row.last_error or "STALE_PROCESSING_RECLAIMED_NO_INTENT"
                )
                retried += 1
        if rows:
            self._session.flush()
        return ambiguous + retried

    def claim_batch(
        self,
        *,
        worker_id: str,
        batch_size: int = 20,
        now: datetime | None = None,
        lease_ttl: timedelta | None = None,
        paper_only: bool = False,
        live_only: bool = False,
    ) -> list[OrderOutbox]:
        if paper_only and live_only:
            raise ValueError("paper_only and live_only are mutually exclusive")
        current = now or datetime.now(timezone.utc)
        ttl = lease_ttl or default_lease_ttl()

        conditions = [
            OrderOutbox.status_code.in_(
                [
                    OutboxStatus.PENDING.value,
                    OutboxStatus.RETRY.value,
                ]
            ),
            or_(
                OrderOutbox.next_retry_at.is_(None),
                OrderOutbox.next_retry_at <= current,
            ),
        ]
        env_expr = OrderOutbox.payload_json["environment"].astext
        if paper_only:
            # LIVE Outbox와 분리 — Paper + Kiwoom MOCK만 claim (LIVE 굶주림/혼입 방지)
            conditions.append(
                or_(
                    and_(
                        OrderOutbox.user_broker_account_id.is_(None),
                        or_(
                            env_expr.is_(None),
                            env_expr == "",
                            env_expr == "PAPER",
                        ),
                    ),
                    and_(
                        env_expr == "MOCK",
                        OrderOutbox.broker_code == "KIWOOM",
                    ),
                )
            )
        elif live_only:
            # 자동 LIVE / Smoke LIVE outbox만 — Paper worker와 claim 분리
            conditions.append(env_expr == "LIVE")

        order_clause = (
            OrderOutbox.outbox_id.desc()
            if paper_only
            else OrderOutbox.outbox_id.asc()
        )
        stmt = (
            select(OrderOutbox)
            .where(*conditions)
            # Paper worker: 최신 건 우선으로 공유 DB 적체 시 굶주림 완화
            .order_by(order_clause)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        rows = list(self._session.scalars(stmt))
        for row in rows:
            row.fencing_token = int(row.fencing_token or 0) + 1
            row.status_code = OutboxStatus.PROCESSING.value
            row.locked_at = current
            row.locked_by = worker_id
            row.lease_expires_at = current + ttl
            record_outbox_audit(
                self._session,
                event_type="OUTBOX_CLAIMED",
                detail={
                    "outbox_id": row.outbox_id,
                    "fencing_token": row.fencing_token,
                    "worker_id": worker_id,
                    "paper_only": paper_only,
                    "live_only": live_only,
                },
                actor=worker_id,
            )
        self._session.flush()
        return rows

    def claim_one(
        self,
        *,
        outbox_id: int,
        worker_id: str,
        now: datetime | None = None,
        lease_ttl: timedelta | None = None,
    ) -> OrderOutbox | None:
        """특정 outbox 1건만 claim — smoke one-shot 전용.

        PENDING/RETRY 이고 retry 시각이 도래한 행만. 다른 건은 건드리지 않는다.
        """

        current = now or datetime.now(timezone.utc)
        ttl = lease_ttl or default_lease_ttl()
        stmt = (
            select(OrderOutbox)
            .where(
                OrderOutbox.outbox_id == int(outbox_id),
                OrderOutbox.status_code.in_(
                    [
                        OutboxStatus.PENDING.value,
                        OutboxStatus.RETRY.value,
                    ]
                ),
                or_(
                    OrderOutbox.next_retry_at.is_(None),
                    OrderOutbox.next_retry_at <= current,
                ),
            )
            .with_for_update(skip_locked=True)
        )
        row = self._session.scalar(stmt)
        if row is None:
            return None
        row.fencing_token = int(row.fencing_token or 0) + 1
        row.status_code = OutboxStatus.PROCESSING.value
        row.locked_at = current
        row.locked_by = worker_id
        row.lease_expires_at = current + ttl
        record_outbox_audit(
            self._session,
            event_type="OUTBOX_CLAIMED",
            detail={
                "outbox_id": row.outbox_id,
                "fencing_token": row.fencing_token,
                "worker_id": worker_id,
                "claim_mode": "ONE_SHOT",
            },
            actor=worker_id,
        )
        self._session.flush()
        return row

    def create_dispatch_intent(
        self,
        *,
        entity: OrderOutbox,
        fencing_token: int,
        worker_id: str,
        request_hash: str,
    ) -> None:
        """Broker 호출 전 영속 Intent — Commit 후에만 Adapter 호출."""

        assert_fencing_allows_mutation(
            entity,
            expected_token=fencing_token,
            worker_id=worker_id,
        )
        if entity.request_hash and entity.request_hash != request_hash:
            entity.status_code = OutboxStatus.MANUAL_REVIEW.value
            entity.manual_review_reason = "REQUEST_HASH_MISMATCH"
            record_outbox_audit(
                self._session,
                event_type="OUTBOX_RETRY_BLOCKED",
                detail={
                    "outbox_id": entity.outbox_id,
                    "reason": "REQUEST_HASH_MISMATCH",
                },
            )
            self._session.flush()
            raise OutboxFencingError("REQUEST_HASH_MISMATCH")

        entity.request_hash = request_hash
        entity.dispatch_intent_at = datetime.now(timezone.utc)
        if not entity.client_order_id:
            entity.client_order_id = str(
                (entity.payload_json or {}).get("client_order_id") or ""
            ).strip() or None
        record_outbox_audit(
            self._session,
            event_type="OUTBOX_DISPATCH_INTENT_CREATED",
            detail={
                "outbox_id": entity.outbox_id,
                "fencing_token": fencing_token,
                "request_hash": request_hash[:16],
                "client_order_id": entity.client_order_id,
            },
            actor=worker_id,
        )
        self._session.flush()

    def mark_done(
        self,
        *,
        entity: OrderOutbox,
        fencing_token: int | None = None,
        worker_id: str | None = None,
    ) -> None:
        if fencing_token is not None and worker_id is not None:
            try:
                assert_fencing_allows_mutation(
                    entity,
                    expected_token=fencing_token,
                    worker_id=worker_id,
                )
            except OutboxFencingError:
                record_outbox_audit(
                    self._session,
                    event_type="OUTBOX_STALE_RESPONSE_IGNORED",
                    detail={
                        "outbox_id": entity.outbox_id,
                        "fencing_token": fencing_token,
                        "action": "mark_done",
                    },
                )
                return
        now = datetime.now(timezone.utc)
        entity.status_code = OutboxStatus.DONE.value
        entity.processed_at = now
        entity.next_retry_at = None
        entity.locked_at = None
        entity.locked_by = None
        entity.lease_expires_at = None
        entity.last_error = None
        self._session.flush()

    def mark_ambiguous(
        self,
        *,
        entity: OrderOutbox,
        reason: str,
        fencing_token: int | None = None,
        worker_id: str | None = None,
    ) -> None:
        if fencing_token is not None and worker_id is not None:
            try:
                assert_fencing_allows_mutation(
                    entity,
                    expected_token=fencing_token,
                    worker_id=worker_id,
                )
            except OutboxFencingError:
                record_outbox_audit(
                    self._session,
                    event_type="OUTBOX_STALE_RESPONSE_IGNORED",
                    detail={
                        "outbox_id": entity.outbox_id,
                        "fencing_token": fencing_token,
                        "action": "mark_ambiguous",
                    },
                )
                return
        now = datetime.now(timezone.utc)
        entity.status_code = OutboxStatus.AMBIGUOUS.value
        entity.ambiguous_at = now
        entity.confirmation_status = "BROKER_CONFIRMATION_REQUIRED"
        entity.last_error = reason[:500]
        entity.locked_at = None
        entity.locked_by = None
        entity.lease_expires_at = None
        record_outbox_audit(
            self._session,
            event_type="OUTBOX_DISPATCH_AMBIGUOUS",
            detail={"outbox_id": entity.outbox_id, "reason": reason[:200]},
        )
        self._session.flush()

    def mark_retry(
        self,
        *,
        entity: OrderOutbox,
        next_retry_at: datetime,
        error_message: str,
        fencing_token: int | None = None,
        worker_id: str | None = None,
        allow_after_intent: bool = False,
    ) -> None:
        if entity.dispatch_intent_at is not None and not allow_after_intent:
            # Broker 호출 가능 구간 이후는 자동 RETRY 금지
            self.mark_ambiguous(
                entity=entity,
                reason=f"RETRY_BLOCKED_AFTER_INTENT:{error_message}",
                fencing_token=fencing_token,
                worker_id=worker_id,
            )
            record_outbox_audit(
                self._session,
                event_type="OUTBOX_RETRY_BLOCKED",
                detail={
                    "outbox_id": entity.outbox_id,
                    "reason": "dispatch_intent_present",
                },
            )
            return
        if fencing_token is not None and worker_id is not None:
            try:
                assert_fencing_allows_mutation(
                    entity,
                    expected_token=fencing_token,
                    worker_id=worker_id,
                )
            except OutboxFencingError:
                record_outbox_audit(
                    self._session,
                    event_type="OUTBOX_STALE_RESPONSE_IGNORED",
                    detail={
                        "outbox_id": entity.outbox_id,
                        "fencing_token": fencing_token,
                        "action": "mark_retry",
                    },
                )
                return
        entity.retry_count += 1
        entity.status_code = OutboxStatus.RETRY.value
        entity.next_retry_at = next_retry_at
        entity.locked_at = None
        entity.locked_by = None
        entity.lease_expires_at = None
        entity.last_error = error_message
        self._session.flush()

    def mark_failed(
        self,
        *,
        entity: OrderOutbox,
        error_message: str,
        fencing_token: int | None = None,
        worker_id: str | None = None,
    ) -> None:
        if fencing_token is not None and worker_id is not None:
            try:
                assert_fencing_allows_mutation(
                    entity,
                    expected_token=fencing_token,
                    worker_id=worker_id,
                )
            except OutboxFencingError:
                record_outbox_audit(
                    self._session,
                    event_type="OUTBOX_STALE_RESPONSE_IGNORED",
                    detail={
                        "outbox_id": entity.outbox_id,
                        "fencing_token": fencing_token,
                        "action": "mark_failed",
                    },
                )
                return
        entity.retry_count += 1
        entity.status_code = OutboxStatus.FAILED.value
        entity.next_retry_at = None
        entity.locked_at = None
        entity.locked_by = None
        entity.lease_expires_at = None
        entity.last_error = error_message
        self._session.flush()

    def approve_manual_retry(
        self,
        *,
        outbox_id: int,
        reason: str,
        actor: str,
    ) -> OrderOutbox:
        """관리자 승인 재시도 — Ambiguous 확인 후에만 RETRY."""

        entity = self.get(outbox_id)
        if entity is None:
            raise LookupError("Outbox not found")
        if entity.status_code not in {
            OutboxStatus.AMBIGUOUS.value,
            OutboxStatus.MANUAL_REVIEW.value,
            OutboxStatus.FAILED.value,
        }:
            raise PermissionError(
                f"manual retry not allowed from {entity.status_code}"
            )
        if entity.confirmation_status not in {
            "ORDER_ABSENT_CONFIRMED",
            "ADMIN_FORCE_RETRY",
        }:
            raise PermissionError(
                "Broker confirmation ORDER_ABSENT_CONFIRMED required"
            )
        entity.status_code = OutboxStatus.RETRY.value
        entity.retry_count = 0
        entity.next_retry_at = datetime.now(timezone.utc)
        entity.dispatch_intent_at = None
        entity.ambiguous_at = None
        entity.manual_review_reason = reason[:500]
        entity.last_error = None
        record_outbox_audit(
            self._session,
            event_type="OUTBOX_MANUAL_REVIEW_CREATED",
            detail={
                "outbox_id": outbox_id,
                "action": "approve_retry",
                "reason": reason[:200],
            },
            actor=actor,
        )
        self._session.flush()
        return entity

    def retry_failed(self, *, outbox_id: int) -> OrderOutbox:
        """레거시 API — FAILED만 단순 RETRY (intent 없는 경우)."""

        entity = self.get(outbox_id)
        if entity is None:
            raise LookupError("Outbox not found")
        if entity.dispatch_intent_at is not None:
            raise PermissionError(
                "Use approve_manual_retry after broker confirmation"
            )
        entity.status_code = OutboxStatus.RETRY.value
        entity.retry_count = 0
        entity.next_retry_at = datetime.now(timezone.utc)
        entity.last_error = None
        self._session.flush()
        return entity
