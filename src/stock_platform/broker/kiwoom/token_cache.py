from __future__ import annotations

from datetime import datetime, timedelta
from threading import RLock

from stock_platform.broker.kiwoom.token_client import (
    KiwoomAccessToken,
    KiwoomTokenClient,
)


class KiwoomTokenCache:
    def __init__(
        self,
        token_client: KiwoomTokenClient,
        *,
        refresh_margin_seconds: int = 300,
    ) -> None:
        self._token_client = token_client
        self._refresh_margin = timedelta(
            seconds=refresh_margin_seconds
        )
        self._cached: KiwoomAccessToken | None = None
        self._lock = RLock()

    def get(self) -> KiwoomAccessToken:
        with self._lock:
            if self._is_valid(self._cached):
                return self._cached  # type: ignore[return-value]

            self._cached = self._token_client.issue()
            return self._cached

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None

    def _is_valid(
        self,
        token: KiwoomAccessToken | None,
    ) -> bool:
        if token is None:
            return False

        now = datetime.now(token.expires_at.tzinfo)
        return now + self._refresh_margin < token.expires_at
