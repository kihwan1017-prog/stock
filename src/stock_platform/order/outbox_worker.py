from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, sessionmaker

from stock_platform.operation.idempotency_repository import (
    PostgreSqlIdempotencyRepository,
)
from stock_platform.order.outbox_dispatcher import (
    OrderOutboxDispatcher,
)
from stock_platform.order.outbox_repository import (
    OrderOutboxRepository,
)


@dataclass(frozen=True, slots=True)
class OutboxRunSummary:
    claimed: int
    succeeded: int
    retried: int
    failed: int


class OrderOutboxWorker:
    RETRY_DELAYS_SECONDS = (
        5,
        15,
        30,
        60,
        300,
    )

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        dispatcher: OrderOutboxDispatcher,
        worker_id: str,
        batch_size: int = 20,
    ) -> None:
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._worker_id = worker_id
        self._batch_size = batch_size

    def run_once(self) -> OutboxRunSummary:
        claimed = 0
        succeeded = 0
        retried = 0
        failed = 0

        with self._session_factory() as session:
            repository = OrderOutboxRepository(
                session
            )
            rows = repository.claim_batch(
                worker_id=self._worker_id,
                batch_size=self._batch_size,
            )
            claimed = len(rows)
            session.commit()

        for claimed_row in rows:
            with self._session_factory() as session:
                repository = OrderOutboxRepository(
                    session
                )
                idempotency = (
                    PostgreSqlIdempotencyRepository(
                        session
                    )
                )
                entity = repository.get(
                    claimed_row.outbox_id
                )
                if entity is None:
                    continue

                try:
                    payload = entity.payload_json
                    request_hash = (
                        idempotency.request_hash(payload)
                    )
                    record = idempotency.begin(
                        idempotency_key=(
                            entity.idempotency_key
                        ),
                        request_hash=request_hash,
                    )

                    if record.status_code == "COMPLETED":
                        repository.mark_done(
                            entity=entity
                        )
                        succeeded += 1
                        session.commit()
                        continue

                    result = self._dispatcher.dispatch(
                        event_type=entity.event_type,
                        payload=payload,
                        idempotency_key=(
                            entity.idempotency_key
                        ),
                    )

                    if not result["accepted"]:
                        raise RuntimeError(
                            result.get(
                                "reject_message"
                            )
                            or "Broker rejected order"
                        )

                    idempotency.complete(
                        idempotency_key=(
                            entity.idempotency_key
                        ),
                        result_json=result,
                    )
                    repository.mark_done(
                        entity=entity
                    )
                    succeeded += 1
                    session.commit()
                except Exception as exc:
                    session.rollback()

                    with self._session_factory() as retry_session:
                        retry_repository = (
                            OrderOutboxRepository(
                                retry_session
                            )
                        )
                        retry_entity = (
                            retry_repository.get(
                                claimed_row.outbox_id
                            )
                        )
                        if retry_entity is None:
                            continue

                        if (
                            retry_entity.retry_count + 1
                            >= retry_entity.max_retry_count
                        ):
                            retry_repository.mark_failed(
                                entity=retry_entity,
                                error_message=str(exc),
                            )
                            failed += 1
                        else:
                            retry_repository.mark_retry(
                                entity=retry_entity,
                                next_retry_at=(
                                    datetime.now(
                                        timezone.utc
                                    )
                                    + timedelta(
                                        seconds=self._retry_delay(
                                            retry_entity.retry_count
                                        )
                                    )
                                ),
                                error_message=str(exc),
                            )
                            retried += 1

                        retry_session.commit()

        return OutboxRunSummary(
            claimed=claimed,
            succeeded=succeeded,
            retried=retried,
            failed=failed,
        )

    @classmethod
    def _retry_delay(
        cls,
        retry_count: int,
    ) -> int:
        index = min(
            retry_count,
            len(cls.RETRY_DELAYS_SECONDS) - 1,
        )
        return cls.RETRY_DELAYS_SECONDS[index]
