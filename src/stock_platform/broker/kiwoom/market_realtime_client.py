"""KIWOOM 시장 시세 WebSocket 전용 client. 주문체결 WS와 분리."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import websockets

from stock_platform.broker.kiwoom.market_realtime_contract import (
    MARKET_TRADE_TYPE,
    MOCK_FEED_FALLBACK_ON_REAL_WS_DOWN,
)
from stock_platform.broker.kiwoom.market_ws_parser import (
    build_login_payload,
    build_market_reg_payload,
    build_market_remove_payload,
    is_ping,
    login_ack_ok,
    parse_market_message,
    reg_ack_ok,
)
from stock_platform.broker.kiwoom.token_cache import KiwoomTokenCache
from stock_platform.broker.kiwoom.ws_config import KiwoomMarketWebSocketConfig
from stock_platform.realtime.models import RealtimeQuote

logger = logging.getLogger(__name__)

QuoteHandler = Callable[[RealtimeQuote], Awaitable[None]]


class KiwoomMarketRealtimeClient:
    """connect / LOGIN / REG 0B / PING echo / reconnect+resubscribe / shutdown."""

    def __init__(
        self,
        *,
        config: KiwoomMarketWebSocketConfig,
        token_cache: KiwoomTokenCache,
        quote_handler: QuoteHandler | None = None,
        connect_factory: Callable[..., Any] | None = None,
        login_timeout_seconds: float = 10.0,
        ack_timeout_seconds: float = 10.0,
        generation_id: int = 0,
    ) -> None:
        self._config = config
        self._token_cache = token_cache
        self._quote_handler = quote_handler
        self._connect_factory = connect_factory or websockets.connect
        self._login_timeout = login_timeout_seconds
        self._ack_timeout = ack_timeout_seconds
        self._generation_id = int(generation_id)
        self._stop_event = asyncio.Event()
        self._symbols: set[str] = set()
        self._connected = False
        self._authenticated = False
        self._login_ack = False
        self._reg_ack = False
        self._subscription_count = 0
        self._event_count = 0
        self._last_event_at: datetime | None = None
        self._last_frame_at: datetime | None = None
        self._last_ping_at: datetime | None = None
        self._frame_count = 0
        self._last_error: str | None = None
        self._reconnect_count = 0
        self._socket: Any | None = None
        self._connect_at: datetime | None = None
        self._subscribe_at: datetime | None = None
        self._first_tick_at: datetime | None = None
        self._disconnect_at: datetime | None = None
        self._close_code: int | None = None
        self._close_reason: str | None = None
        self._exit_reason: str | None = None

    def note_exit_reason(self, reason: str) -> None:
        self._exit_reason = str(reason or "").strip() or None

    def _note_inbound_frame(self, message: dict[str, Any]) -> None:
        """수신 JSON frame 시각 — PING 포함 (market tick activity와 분리)."""

        now = datetime.now(timezone.utc)
        self._last_frame_at = now
        self._frame_count += 1
        if is_ping(message):
            self._last_ping_at = now

    def set_quote_handler(self, handler: QuoteHandler | None) -> None:
        self._quote_handler = handler

    def subscribe_symbols(self, symbols: list[str] | set[str]) -> None:
        for raw in symbols:
            code = str(raw or "").strip().upper()
            if code:
                self._symbols.add(code)
        self._subscription_count = len(self._symbols)

    def unsubscribe_symbols(self, symbols: list[str] | set[str]) -> None:
        for raw in symbols:
            self._symbols.discard(str(raw or "").strip().upper())
        self._subscription_count = len(self._symbols)

    async def run_forever(self) -> None:
        delay = self._config.reconnect_min_seconds
        while not self._stop_event.is_set():
            try:
                await self._connect_once(wait_forever=True)
                delay = self._config.reconnect_min_seconds
            except asyncio.CancelledError:
                self.note_exit_reason("TASK_CANCELLED")
                raise
            except Exception as exc:  # noqa: BLE001
                self._connected = False
                self._authenticated = False
                self._last_error = str(exc)[:200]
                if self._exit_reason is None:
                    self.note_exit_reason(type(exc).__name__)
                logger.warning(
                    "kiwoom_market_ws_disconnected env=%s gen=%s err=%s",
                    self._config.environment,
                    self._generation_id,
                    exc.__class__.__name__,
                )
                if MOCK_FEED_FALLBACK_ON_REAL_WS_DOWN:
                    self._last_error = "MOCK_FALLBACK_FORBIDDEN"
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=delay,
                    )
                except TimeoutError:
                    pass
                if self._stop_event.is_set():
                    break
                self._reconnect_count += 1
                delay = min(
                    delay * 2,
                    self._config.reconnect_max_seconds,
                )

    async def probe_login_and_register(
        self,
        symbols: list[str],
        *,
        idle_seconds: float = 1.0,
    ) -> dict[str, Any]:
        """장외 LOGIN/REG ACK 1회. reconnect loop 없음. 주문 REG 없음."""

        self.subscribe_symbols(symbols)
        before = self._event_count
        try:
            await self._connect_once(
                wait_forever=False,
                idle_after_ack_seconds=idle_seconds,
            )
        finally:
            await self.shutdown()
        return {
            **self.status(),
            "event_count_before": before,
            "event_count_after": self._event_count,
            "tick_received": self._event_count > before,
        }

    async def shutdown(self) -> None:
        self._stop_event.set()
        socket = self._socket
        if socket is not None and self._symbols:
            try:
                await socket.send(
                    json.dumps(
                        build_market_remove_payload(self._symbols),
                        ensure_ascii=False,
                    )
                )
            except Exception:  # noqa: BLE001
                pass
        self._connected = False
        self._authenticated = False
        self._socket = None

    def status(self) -> dict[str, Any]:
        return {
            "environment": self._config.environment,
            "endpoint_host": self._config.url,
            "ws_path": self._config.path,
            "market_type": MARKET_TRADE_TYPE,
            "generation_id": self._generation_id,
            "connected": self._connected,
            "authenticated": self._authenticated,
            "login_ack": self._login_ack,
            "reg_ack": self._reg_ack,
            "subscription_count": self._subscription_count,
            "symbols": sorted(self._symbols),
            "event_count": self._event_count,
            "frame_count": self._frame_count,
            "last_frame_at": (
                self._last_frame_at.isoformat() if self._last_frame_at else None
            ),
            "last_ping_at": (
                self._last_ping_at.isoformat() if self._last_ping_at else None
            ),
            "last_event_at": (
                self._last_event_at.isoformat()
                if self._last_event_at
                else None
            ),
            "last_error": self._last_error,
            "reconnect_count": self._reconnect_count,
            "mock_fallback_enabled": MOCK_FEED_FALLBACK_ON_REAL_WS_DOWN,
            "lifecycle": {
                "generation_id": self._generation_id,
                "connect_at": (
                    self._connect_at.isoformat() if self._connect_at else None
                ),
                "subscribe_at": (
                    self._subscribe_at.isoformat() if self._subscribe_at else None
                ),
                "first_tick_at": (
                    self._first_tick_at.isoformat() if self._first_tick_at else None
                ),
                "last_tick_at": (
                    self._last_event_at.isoformat() if self._last_event_at else None
                ),
                "last_frame_at": (
                    self._last_frame_at.isoformat() if self._last_frame_at else None
                ),
                "last_ping_at": (
                    self._last_ping_at.isoformat() if self._last_ping_at else None
                ),
                "frame_count": self._frame_count,
                "disconnect_at": (
                    self._disconnect_at.isoformat() if self._disconnect_at else None
                ),
                "close_code": self._close_code,
                "close_reason": self._close_reason,
                "exit_reason": self._exit_reason,
                "tick_count": self._event_count,
            },
        }

    async def _connect_once(
        self,
        *,
        wait_forever: bool,
        idle_after_ack_seconds: float = 0.0,
    ) -> None:
        token = self._token_cache.get()
        endpoint = self._config.endpoint
        try:
            async with self._connect_factory(
                endpoint,
                ping_interval=self._config.ping_interval_seconds,
                ping_timeout=self._config.ping_timeout_seconds,
                max_size=2**22,
            ) as socket:
                self._socket = socket
                self._connected = True
                self._connect_at = datetime.now(timezone.utc)
                self._login_ack = False
                self._reg_ack = False
                self._authenticated = False
                await socket.send(
                    json.dumps(
                        build_login_payload(token.token),
                        ensure_ascii=False,
                    )
                )
                stream = socket.__aiter__()
                login_deadline = (
                    asyncio.get_running_loop().time() + self._login_timeout
                )
                registered = False
                idle_deadline: float | None = None
                while not self._stop_event.is_set():
                    timeout: float | None = None
                    now = asyncio.get_running_loop().time()
                    if not self._login_ack:
                        timeout = max(0.05, login_deadline - now)
                        if now > login_deadline:
                            raise TimeoutError("KIWOOM market WS LOGIN ACK timeout")
                    elif (
                        not wait_forever
                        and idle_deadline is not None
                        and now >= idle_deadline
                    ):
                        break
                    elif not wait_forever and idle_deadline is not None:
                        timeout = max(0.05, idle_deadline - now)
                    try:
                        raw = await asyncio.wait_for(
                            stream.__anext__(),
                            timeout=timeout,
                        )
                    except TimeoutError:
                        if not self._login_ack:
                            raise TimeoutError(
                                "KIWOOM market WS LOGIN ACK timeout"
                            )
                        if not wait_forever and self._reg_ack:
                            break
                        continue
                    except StopAsyncIteration:
                        break
                    message = (
                        json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                    )
                    if not isinstance(message, dict):
                        continue
                    self._note_inbound_frame(message)
                    if is_ping(message):
                        await socket.send(json.dumps(message))
                        continue
                    if not self._login_ack:
                        if login_ack_ok(message):
                            self._login_ack = True
                            self._authenticated = True
                            if self._symbols:
                                await socket.send(
                                    json.dumps(
                                        build_market_reg_payload(self._symbols),
                                        ensure_ascii=False,
                                    )
                                )
                                registered = True
                            continue
                        if str(message.get("trnm") or "").upper() == "LOGIN":
                            self._last_error = "LOGIN_ACK_FAILED"
                            raise RuntimeError("KIWOOM market WS LOGIN ACK failed")
                        continue
                    if registered and not self._reg_ack and reg_ack_ok(message):
                        self._reg_ack = True
                        self._subscribe_at = datetime.now(timezone.utc)
                        if not wait_forever:
                            idle_deadline = (
                                asyncio.get_running_loop().time()
                                + max(0.0, idle_after_ack_seconds)
                            )
                        continue
                    quotes = parse_market_message(
                        message,
                        environment=self._config.environment,
                    )
                    for quote in quotes:
                        self._event_count += 1
                        now_tick = datetime.now(timezone.utc)
                        self._last_event_at = now_tick
                        if self._first_tick_at is None:
                            self._first_tick_at = now_tick
                        if self._quote_handler is not None:
                            await self._quote_handler(quote)
                if wait_forever and not self._stop_event.is_set():
                    raise RuntimeError("KIWOOM market WS stream ended")
        except websockets.exceptions.ConnectionClosed as exc:
            self._close_code = int(getattr(exc, "code", 0) or 0)
            self._close_reason = str(getattr(exc, "reason", "") or "")[:200] or None
            if self._exit_reason is None:
                initiator = (
                    "CLIENT_INITIATED"
                    if self._stop_event.is_set()
                    else "SERVER_INITIATED"
                )
                self.note_exit_reason(initiator)
            raise
        finally:
            self._connected = False
            self._socket = None
            self._disconnect_at = datetime.now(timezone.utc)
            if self._exit_reason is None and self._stop_event.is_set():
                self.note_exit_reason("CLIENT_SHUTDOWN")
            logger.info(
                "kiwoom_market_ws_epoch_end gen=%s ticks=%s close_code=%s exit=%s",
                self._generation_id,
                self._event_count,
                self._close_code,
                self._exit_reason,
            )
