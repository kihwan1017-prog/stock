class UpbitError(RuntimeError):
    """Base exception for Upbit API failures."""


class UpbitRequestError(UpbitError):
    """Raised when an Upbit REST request fails."""


class UpbitRateLimitError(UpbitRequestError):
    """Raised when Upbit rejects a request due to rate limiting."""
