from __future__ import annotations

import json
import os

from stock_platform.broker.kiwoom.auth import (
    KiwoomTokenProvider,
)
from stock_platform.broker.kiwoom.config import (
    KiwoomBrokerConfig,
)
from stock_platform.broker.kiwoom.ws_client import (
    KiwoomOrderExecutionWebSocketClient,
)
from stock_platform.broker.order_event_bus import (
    BrokerOrderEventBus,
)


kiwoom_order_event_bus = BrokerOrderEventBus()


def build_kiwoom_order_websocket(
    handler,
) -> KiwoomOrderExecutionWebSocketClient:
    use_mock = (
        os.getenv(
            "KIWOOM_USE_MOCK",
            "true",
        ).lower()
        == "true"
    )

    config = KiwoomBrokerConfig(
        app_key=os.getenv("KIWOOM_APP_KEY", ""),
        secret_key=os.getenv(
            "KIWOOM_SECRET_KEY",
            "",
        ),
        use_mock=use_mock,
        live_order_enabled=False,
    )
    config.validate()

    default_url = (
        "wss://mockapi.kiwoom.com:10000"
        if use_mock
        else "wss://api.kiwoom.com:10000"
    )

    websocket_url = os.getenv(
        "KIWOOM_ORDER_WS_URL",
        default_url,
    )
    path = os.getenv(
        "KIWOOM_ORDER_WS_PATH",
        "",
    ).strip()

    if path:
        websocket_url = (
            websocket_url.rstrip("/")
            + "/"
            + path.lstrip("/")
        )

    subscribe_raw = os.getenv(
        "KIWOOM_ORDER_WS_SUBSCRIBE_JSON",
        "",
    )

    if not subscribe_raw:
        raise ValueError(
            "KIWOOM_ORDER_WS_SUBSCRIBE_JSON must be "
            "copied from the current Kiwoom official "
            "WebSocket order-execution example"
        )

    subscribe_message = json.loads(subscribe_raw)

    return KiwoomOrderExecutionWebSocketClient(
        token_provider=KiwoomTokenProvider(
            config=config
        ),
        websocket_url=websocket_url,
        subscribe_message=subscribe_message,
        handler=handler,
    )
