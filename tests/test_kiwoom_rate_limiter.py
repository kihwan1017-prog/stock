from stock_platform.broker.kiwoom.rate_limiter import (
    SlidingWindowRateLimiter,
)


def test_limiter_accepts_calls():
    limiter = SlidingWindowRateLimiter(
        max_calls=5,
        period_seconds=0.01,
    )

    for _ in range(6):
        limiter.acquire()
