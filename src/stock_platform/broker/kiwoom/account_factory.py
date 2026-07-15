from __future__ import annotations

import os

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
    config = KiwoomBrokerConfig(
        app_key=os.getenv("KIWOOM_APP_KEY", ""),
        secret_key=os.getenv(
            "KIWOOM_SECRET_KEY",
            "",
        ),
        use_mock=(
            os.getenv(
                "KIWOOM_USE_MOCK",
                "true",
            ).lower()
            == "true"
        ),
        live_order_enabled=False,
    )
    config.validate()

    token_provider = KiwoomTokenProvider(
        config=config
    )
    rest_client = KiwoomRestClient(
        config=config,
        token_provider=token_provider,
    )
    return KiwoomAccountClient(rest_client)
