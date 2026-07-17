from datetime import datetime, timedelta

from stock_platform.broker.kiwoom.token_cache import (
    KiwoomTokenCache,
)
from stock_platform.broker.kiwoom.token_client import (
    KiwoomAccessToken,
)


class TokenClient:
    def __init__(self):
        self.calls = 0

    def issue(self):
        self.calls += 1
        return KiwoomAccessToken(
            token=f"TOKEN-{self.calls}",
            token_type="bearer",
            expires_at=datetime.now()
            + timedelta(hours=1),
        )


def test_token_is_cached():
    client = TokenClient()
    cache = KiwoomTokenCache(client)

    assert cache.get().token == "TOKEN-1"
    assert cache.get().token == "TOKEN-1"
    assert client.calls == 1


def test_invalidate_issues_new_token():
    client = TokenClient()
    cache = KiwoomTokenCache(client)

    cache.get()
    cache.invalidate()

    assert cache.get().token == "TOKEN-2"
