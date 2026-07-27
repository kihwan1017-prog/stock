"""STEP 8-5-22 Outbox fencing unit tests (no broker I/O)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.order.outbox_fencing import (
    OutboxFencingError,
    assert_fencing_allows_mutation,
    stable_request_hash,
)
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.order.outbox_repository import OrderOutboxRepository
from tests.migration_helpers import (
    alembic_current_head,
    assert_revision_exists,
)


def test_step8_5_22_revision_head() -> None:
    assert_revision_exists("i2c3d4e5f6a7")
    assert_revision_exists("m0a1b2c3d4e5")
    assert_revision_exists("n3d4e5f6a7b8")
    assert_revision_exists("o4e5f6a7b8c9")
    assert_revision_exists("p5f6a7b8c9d0")
    assert_revision_exists("q6a7b8c9d0e1")
    assert_revision_exists("r7b8c9d0e1f2")
    assert_revision_exists("s8c9d0e1f2a3")
    assert_revision_exists("w3d4e5f6a7b8")
    assert_revision_exists("x4e5f6a7b8c9")
    assert_revision_exists("y5f6a7b8c9d0")
    assert_revision_exists("z6a7b8c9d0e1")
    assert_revision_exists("aa1b2c3d4e5f")
    assert alembic_current_head() == "ae5f6a7b8c9d"


def test_request_hash_stable() -> None:
    a = {"b": 1, "a": 2}
    b = {"a": 2, "b": 1}
    assert stable_request_hash(a) == stable_request_hash(b)


def test_fencing_rejects_stale_token() -> None:
    entity = OrderOutbox(
        order_id=1,
        event_type="SUBMIT_ORDER",
        idempotency_key="k",
        payload_json={},
        status_code=OutboxStatus.PROCESSING.value,
        fencing_token=2,
        locked_by="worker-b",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    with pytest.raises(OutboxFencingError):
        assert_fencing_allows_mutation(
            entity, expected_token=1, worker_id="worker-a"
        )


def test_fencing_rejects_expired_lease() -> None:
    entity = OrderOutbox(
        order_id=1,
        event_type="SUBMIT_ORDER",
        idempotency_key="k",
        payload_json={},
        status_code=OutboxStatus.PROCESSING.value,
        fencing_token=1,
        locked_by="w",
        lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    with pytest.raises(OutboxFencingError):
        assert_fencing_allows_mutation(
            entity, expected_token=1, worker_id="w"
        )


def test_reclaim_after_intent_goes_ambiguous() -> None:
    session = MagicMock()
    entity = OrderOutbox(
        order_id=1,
        event_type="SUBMIT_ORDER",
        idempotency_key="k",
        payload_json={},
        status_code=OutboxStatus.PROCESSING.value,
        fencing_token=3,
        locked_by="w",
        locked_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        dispatch_intent_at=datetime.now(timezone.utc) - timedelta(minutes=2),
    )
    session.scalars.return_value = [entity]
    repo = OrderOutboxRepository(session)
    n = repo.reclaim_stale_processing(stale_after=timedelta(minutes=5))
    assert n == 1
    assert entity.status_code == OutboxStatus.AMBIGUOUS.value


def test_reclaim_without_intent_retries() -> None:
    session = MagicMock()
    entity = OrderOutbox(
        order_id=1,
        event_type="SUBMIT_ORDER",
        idempotency_key="k",
        payload_json={},
        status_code=OutboxStatus.PROCESSING.value,
        fencing_token=1,
        locked_by="w",
        locked_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        dispatch_intent_at=None,
    )
    session.scalars.return_value = [entity]
    repo = OrderOutboxRepository(session)
    n = repo.reclaim_stale_processing(stale_after=timedelta(minutes=5))
    assert n == 1
    assert entity.status_code == OutboxStatus.RETRY.value


def test_mark_done_ignores_stale_fencing() -> None:
    session = MagicMock()
    entity = OrderOutbox(
        order_id=1,
        event_type="SUBMIT_ORDER",
        idempotency_key="k",
        payload_json={},
        status_code=OutboxStatus.PROCESSING.value,
        fencing_token=5,
        locked_by="worker-b",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    repo = OrderOutboxRepository(session)
    repo.mark_done(
        entity=entity, fencing_token=1, worker_id="worker-a"
    )
    # Stale fencing token must not mutate status
    assert entity.status_code == OutboxStatus.PROCESSING.value


def test_hash_mismatch_blocks_intent() -> None:
    session = MagicMock()
    entity = OrderOutbox(
        order_id=1,
        event_type="SUBMIT_ORDER",
        idempotency_key="k",
        payload_json={"x": 1},
        status_code=OutboxStatus.PROCESSING.value,
        fencing_token=1,
        locked_by="w",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        request_hash=stable_request_hash({"x": 1}),
    )
    repo = OrderOutboxRepository(session)
    with pytest.raises(OutboxFencingError):
        repo.create_dispatch_intent(
            entity=entity,
            fencing_token=1,
            worker_id="w",
            request_hash=stable_request_hash({"x": 2}),
        )
    assert entity.status_code == OutboxStatus.MANUAL_REVIEW.value
