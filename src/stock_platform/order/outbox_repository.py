from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from stock_platform.order.outbox_entities import (
    OrderOutbox,
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
        existing = self.get_by_idempotency_key(
            idempotency_key
        )
        if existing is not None:
            return existing

        entity = OrderOutbox(
            order_id=order_id,
            event_type=event_type.value,
            idempotency_key=idempotency_key,
            payload_json=payload_json,
            status_code=OutboxStatus.PENDING.value,
            retry_count=0,
            max_retry_count=max_retry_count,
        )
        self._session.add(entity)
        self._session.flush()
        return entity

    def get(
        self,
        outbox_id: int,
    ) -> OrderOutbox | None:
        return self._session.get(
            OrderOutbox,
            outbox_id,
        )

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> OrderOutbox | None:
        stmt = select(OrderOutbox).where(
            OrderOutbox.idempotency_key
            == idempotency_key
        )
        return self._session.scalar(stmt)

    def claim_batch(
        self,
        *,
        worker_id: str,
        batch_size: int = 20,
        now: datetime | None = None,
    ) -> list[OrderOutbox]:
        current = now or datetime.now(timezone.utc)

        stmt = (
            select(OrderOutbox)
            .where(
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
            .order_by(OrderOutbox.outbox_id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )

        rows = list(
            self._session.scalars(stmt)
        )

        for row in rows:
            row.status_code = (
                OutboxStatus.PROCESSING.value
            )
            row.locked_at = current
            row.locked_by = worker_id

        self._session.flush()
        return rows

    def mark_done(
        self,
        *,
        entity: OrderOutbox,
    ) -> None:
        now = datetime.now(timezone.utc)
        entity.status_code = OutboxStatus.DONE.value
        entity.processed_at = now
        entity.next_retry_at = None
        entity.locked_at = None
        entity.locked_by = None
        entity.last_error = None
        self._session.flush()

    def mark_retry(
        self,
        *,
        entity: OrderOutbox,
        next_retry_at: datetime,
        error_message: str,
    ) -> None:
        entity.retry_count += 1
        entity.status_code = OutboxStatus.RETRY.value
        entity.next_retry_at = next_retry_at
        entity.locked_at = None
        entity.locked_by = None
        entity.last_error = error_message
        self._session.flush()

    def mark_failed(
        self,
        *,
        entity: OrderOutbox,
        error_message: str,
    ) -> None:
        entity.retry_count += 1
        entity.status_code = OutboxStatus.FAILED.value
        entity.next_retry_at = None
        entity.locked_at = None
        entity.locked_by = None
        entity.last_error = error_message
        self._session.flush()

    def retry_failed(
        self,
        *,
        outbox_id: int,
    ) -> OrderOutbox:
        entity = self.get(outbox_id)
        if entity is None:
            raise LookupError("Outbox not found")

        entity.status_code = OutboxStatus.RETRY.value
        entity.retry_count = 0
        entity.next_retry_at = datetime.now(
            timezone.utc
        )
        entity.last_error = None
        self._session.flush()
        return entity
