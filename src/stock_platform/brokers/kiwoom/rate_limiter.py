"""호환 래퍼 — canonical: stock_platform.broker.common.async_rate_limiter"""

from stock_platform.broker.common.async_rate_limiter import (
    AsyncSlidingWindowRateLimiter,
)

__all__ = ["AsyncSlidingWindowRateLimiter"]
