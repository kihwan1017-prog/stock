from stock_platform.broker.idempotency import (
    InMemoryIdempotencyStore,
)


def test_operation_runs_once():
    store = InMemoryIdempotencyStore()
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        return "RESULT"

    first = store.execute_once(
        key="KEY",
        operation=operation,
    )
    second = store.execute_once(
        key="KEY",
        operation=operation,
    )

    assert first == "RESULT"
    assert second == "RESULT"
    assert calls == 1
