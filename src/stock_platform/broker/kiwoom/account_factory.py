from __future__ import annotations

from stock_platform.broker.kiwoom.account_client import (
    KiwoomAccountClient,
)
from stock_platform.broker.kiwoom.auth import (
    KiwoomTokenProvider,
)
from stock_platform.broker.kiwoom.client import (
    KiwoomRestClient,
)
from stock_platform.broker.kiwoom.config import (
    KiwoomBrokerConfig,
)


def build_kiwoom_account_client() -> KiwoomAccountClient:
    config = KiwoomBrokerConfig.from_settings()
    config.validate()

    token_provider = KiwoomTokenProvider(
        config=config
    )
    rest_client = KiwoomRestClient(
        config=config,
        token_provider=token_provider,
    )
    return KiwoomAccountClient(rest_client)
