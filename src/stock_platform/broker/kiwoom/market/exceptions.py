class KiwoomError(RuntimeError):
    """Base exception for Kiwoom REST API failures."""


class KiwoomConfigurationError(KiwoomError):
    """Raised when required Kiwoom configuration is missing."""


class KiwoomAuthenticationError(KiwoomError):
    """Raised when access-token issuance or authentication fails."""


class KiwoomRequestError(KiwoomError):
    """Raised when a Kiwoom REST request fails."""


class KiwoomRateLimitError(KiwoomRequestError):
    """Raised when Kiwoom rejects a request because of rate limiting."""
