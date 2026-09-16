"""STEP 8-5-9 — Realtime Hub / Scope 상수."""

from __future__ import annotations

from enum import StrEnum


class HubConnectionStatus(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    DEGRADED = "DEGRADED"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class ConsumerWarmupStatus(StrEnum):
    PENDING = "PENDING"
    WARMING_UP = "WARMING_UP"
    READY = "READY"
    DEFERRED = "DEFERRED"
    FAILED = "FAILED"


class RealtimeEventType(StrEnum):
    TRADE = "TRADE"
    TICKER = "TICKER"
    ORDERBOOK = "ORDERBOOK"
    CANDLE = "CANDLE"
    MARKET_STATUS = "MARKET_STATUS"


class SignalType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    EXIT = "EXIT"
    HOLD = "HOLD"
    NO_ACTION = "NO_ACTION"
