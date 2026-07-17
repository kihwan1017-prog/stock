from stock_platform.order.outbox_worker import (
    OrderOutboxWorker,
)


def test_retry_delay_policy():
    assert OrderOutboxWorker._retry_delay(0) == 5
    assert OrderOutboxWorker._retry_delay(1) == 15
    assert OrderOutboxWorker._retry_delay(2) == 30
    assert OrderOutboxWorker._retry_delay(3) == 60
    assert OrderOutboxWorker._retry_delay(4) == 300
    assert OrderOutboxWorker._retry_delay(99) == 300
