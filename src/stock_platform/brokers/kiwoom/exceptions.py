"""호환 래퍼 — canonical: stock_platform.broker.kiwoom.market.exceptions"""

from stock_platform.broker.kiwoom.market.exceptions import (
    KiwoomAuthenticationError,
    KiwoomConfigurationError,
    KiwoomError,
    KiwoomRateLimitError,
    KiwoomRequestError,
)

__all__ = [
    "KiwoomAuthenticationError",
    "KiwoomConfigurationError",
    "KiwoomError",
    "KiwoomRateLimitError",
    "KiwoomRequestError",
]
