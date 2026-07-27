"""Outbox claim_batch SKIP LOCKED 동시성 (P1)."""

from __future__ import annotations

import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from stock_platform.common.settings import get_settings
from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.order.outbox_repository import OrderOutboxRepository


@pytest.mark.integration
def test_outbox_claim_batch_skip_locked_no_double_claim() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL 연결 불가: {exc}")

    session = factory()
    order_id: int | None = None
    outbox_id: int | None = None
    try:
        order_id = int(
            session.execute(
                text(
                    """
                    INSERT INTO trading.trading_order (
                        client_order_id, account_id, broker_code,
                        exchange_code, symbol, side_code, order_type_code,
                        order_quantity, remaining_quantity
                    ) VALUES (
                        :cid, 1, 'KIWOOM', 'KRX', '005930', 'BUY', 'LIMIT',
                        1, 1
                    )
                    RETURNING order_id
                    """
                ),
                {"cid": f"race-{uuid4().hex[:16]}"},
            ).scalar_one()
        )
        key = f"race-{uuid4().hex}"
        row = OrderOutbox(
            order_id=order_id,
            event_type="SUBMIT",
            idempotency_key=key,
            payload_json={"test": True},
            status_code=OutboxStatus.PENDING.value,
        )
        session.add(row)
        session.commit()
        outbox_id = int(row.outbox_id)
    except Exception:
        session.rollback()
        pytest.skip("outbox race seed 실패 (스키마/FK)")
        return
    finally:
        session.close()

    assert outbox_id is not None
    claimed_ids: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker(worker_id: str) -> None:
        local = factory()
        try:
            barrier.wait(timeout=5)
            repo = OrderOutboxRepository(local)
            rows = repo.claim_batch(worker_id=worker_id, batch_size=10)
            local.commit()
            with lock:
                claimed_ids.extend(int(r.outbox_id) for r in rows)
        except Exception:
            local.rollback()
            raise
        finally:
            local.close()

    t1 = threading.Thread(target=worker, args=("w1",))
    t2 = threading.Thread(target=worker, args=("w2",))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert claimed_ids.count(outbox_id) == 1

    cleanup = factory()
    try:
        cleanup.execute(
            text(
                "DELETE FROM trading.order_outbox WHERE outbox_id = :id"
            ),
            {"id": outbox_id},
        )
        if order_id is not None:
            cleanup.execute(
                text(
                    "DELETE FROM trading.trading_order WHERE order_id = :id"
                ),
                {"id": order_id},
            )
        cleanup.commit()
    finally:
        cleanup.close()
