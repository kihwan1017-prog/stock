from stock_platform.operation.idempotency_repository import (
    PostgreSqlIdempotencyRepository,
)


def test_request_hash_is_order_independent():
    first = PostgreSqlIdempotencyRepository.request_hash(
        {"symbol": "005930", "quantity": 1}
    )
    second = PostgreSqlIdempotencyRepository.request_hash(
        {"quantity": 1, "symbol": "005930"}
    )

    assert first == second
