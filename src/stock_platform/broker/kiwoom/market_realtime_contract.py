"""공식 KIWOOM 국내주식 실시간 시세 계약 상수.

출처: Kiwoom-Securities/Kiwoom-REST-API
- docs: kiwoom_docs/실시간시세.md
- example: examples/국내주식/실시간시세/subscribe_domestic_stock_trade_async.py
- client: kiwoom/core/ws_client.py

추측 type/code 금지. 주문체결 type=00 과 혼용 금지.
"""

from __future__ import annotations

OFFICIAL_SOURCE = "https://github.com/Kiwoom-Securities/Kiwoom-REST-API"
OFFICIAL_WS_PATH = "/api/dostk/websocket"
OFFICIAL_REAL_WS_HOST = "wss://api.kiwoom.com:10000"
OFFICIAL_MOCK_WS_HOST = "wss://mockapi.kiwoom.com:10000"

# 국내주식 체결(주식체결). 주문체결 00 아님.
MARKET_TRADE_TYPE = "0B"

SOURCE_WEBSOCKET_REAL = "KIWOOM_WEBSOCKET_REAL"
SOURCE_WEBSOCKET_MOCK = "KIWOOM_WEBSOCKET_MOCK"
SOURCE_REST_POLLING = "KIWOOM_REST_POLLING"

# LIVE realtime SoT 는 REAL WS. REST polling 은 diagnostic 전용.
REST_POLLING_IS_LIVE_RUNTIME_SOT = False
MOCK_FEED_FALLBACK_ON_REAL_WS_DOWN = False

FIELD_TRADE_TIME = "20"
FIELD_CURRENT_PRICE = "10"
FIELD_CHANGE_RATE = "12"
FIELD_BEST_ASK = "27"
FIELD_BEST_BID = "28"
FIELD_TRADE_VOLUME = "15"
FIELD_ACCUM_VOLUME = "13"

REASON_REAL_EXECUTION_REQUIRES_REAL_MARKET_DATA = (
    "REAL_EXECUTION_REQUIRES_REAL_MARKET_DATA"
)
REASON_MARKET_DATA_DISCONNECTED = "MARKET_DATA_DISCONNECTED"
REASON_REST_POLLING_NOT_LIVE_SOT = "REST_POLLING_NOT_LIVE_RUNTIME_SOT"
REASON_UNKNOWN_MARKET_SOURCE = "UNKNOWN_MARKET_SOURCE"


def is_official_market_type(type_code: str) -> bool:
    return str(type_code or "").strip().upper() == MARKET_TRADE_TYPE


def source_code_for_environment(environment: str) -> str:
    env = str(environment or "").strip().upper()
    if env == "REAL":
        return SOURCE_WEBSOCKET_REAL
    return SOURCE_WEBSOCKET_MOCK
