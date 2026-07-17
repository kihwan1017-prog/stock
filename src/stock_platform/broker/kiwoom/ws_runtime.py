from __future__ import annotations

import json

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
from stock_platform.common.settings import get_settings


kiwoom_order_event_bus = BrokerOrderEventBus()


def build_kiwoom_order_websocket(
    handler,
) -> KiwoomOrderExecutionWebSocketClient:
    settings = get_settings()
    config = KiwoomBrokerConfig.from_settings()
    config.validate()

    websocket_url = settings.kiwoom_order_ws_url_resolved
    path = settings.kiwoom_order_ws_path.strip()

    if path:
        websocket_url = (
            websocket_url.rstrip("/")
            + "/"
            + path.lstrip("/")
        )

    subscribe_raw = settings.kiwoom_order_ws_subscribe_json.strip()
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
