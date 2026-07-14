from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

from stock_platform.realtime.models import (
    MarketEventType,
    RealtimeQuote,
)


logger = structlog.get_logger(__name__)

QuoteHandler = Callable[[RealtimeQuote], Awaitable[None]]


class UpbitRealtimeClient:
    """
    업비트 공개 WebSocket 현재가 스트림 클라이언트.

    연결이 끊기면 지수 백오프로 자동 재연결한다.
    """

    def __init__(
        self,
        *,
        symbols: list[str],
        handler: QuoteHandler,
        websocket_url: str = "wss://api.upbit.com/websocket/v1",
        ping_interval_seconds: float = 30.0,
        reconnect_max_seconds: float = 60.0,
    ) -> None:
        normalized = sorted(
            {
                symbol.strip().upper()
                for symbol in symbols
                if symbol.strip()
            }
        )
        if not normalized:
            raise ValueError("symbols must not be empty")

        self._symbols = normalized
        self._handler = handler
        self._websocket_url = websocket_url
        self._ping_interval_seconds = ping_interval_seconds
        self._reconnect_max_seconds = reconnect_max_seconds
        self._stop_event = asyncio.Event()
        self._connected = False
        self._last_error: str | None = None
        self._received_count = 0

    async def run_forever(self) -> None:
        retry_seconds = 1.0

        while not self._stop_event.is_set():
            try:
                await self._run_once()
                retry_seconds = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected = False
                self._last_error = str(exc)
                logger.exception(
                    "upbit_realtime_connection_failed",
                    retry_seconds=retry_seconds,
                )

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=retry_seconds,
                    )
                except asyncio.TimeoutError:
                    pass

                retry_seconds = min(
                    retry_seconds * 2,
                    self._reconnect_max_seconds,
                )

    async def _run_once(self) -> None:
        async with websockets.connect(
            self._websocket_url,
            ping_interval=self._ping_interval_seconds,
            ping_timeout=10,
            close_timeout=5,
            max_queue=2048,
        ) as websocket:
            request = [
                {
                    "ticket": str(uuid.uuid4()),
                },
                {
                    "type": "ticker",
                    "codes": self._symbols,
                    "is_only_realtime": True,
                },
                {
                    "format": "DEFAULT",
                },
            ]

            await websocket.send(
                json.dumps(
                    request,
                    ensure_ascii=False,
                )
            )
            self._connected = True
            self._last_error = None

            logger.info(
                "upbit_realtime_connected",
                symbols=self._symbols,
            )

            while not self._stop_event.is_set():
                try:
                    raw_message = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=90,
                    )
                except asyncio.TimeoutError:
                    await websocket.ping()
                    continue
                except ConnectionClosed:
                    break

                payload = self._decode_message(raw_message)
                quote = self._to_quote(payload)
                self._received_count += 1
                await self._handler(quote)

        self._connected = False

    async def stop(self) -> None:
        self._stop_event.set()

    def status(self) -> dict[str, Any]:
        return {
            "exchange_code": "UPBIT",
            "connected": self._connected,
            "symbols": self._symbols,
            "received_count": self._received_count,
            "last_error": self._last_error,
        }

    @staticmethod
    def _decode_message(
        raw_message: str | bytes,
    ) -> dict[str, Any]:
        if isinstance(raw_message, bytes):
            raw_message = raw_message.decode("utf-8")

        payload = json.loads(raw_message)
        if not isinstance(payload, dict):
            raise ValueError(
                "Upbit WebSocket payload must be an object"
            )

        return payload

    @staticmethod
    def _decimal(
        value: Any,
    ) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    @classmethod
    def _to_quote(
        cls,
        payload: dict[str, Any],
    ) -> RealtimeQuote:
        symbol = str(
            payload.get("code")
            or payload.get("market")
            or ""
        ).upper()

        if not symbol:
            raise ValueError(
                "Upbit ticker payload has no code"
            )

        timestamp_value = payload.get("timestamp")
        if timestamp_value is None:
            event_time = datetime.now(timezone.utc)
        else:
            event_time = datetime.fromtimestamp(
                int(timestamp_value) / 1000,
                tz=timezone.utc,
            )

        return RealtimeQuote(
            exchange_code="UPBIT",
            symbol=symbol,
            event_type=MarketEventType.TICKER,
            trade_price=Decimal(
                str(payload["trade_price"])
            ),
            opening_price=cls._decimal(
                payload.get("opening_price")
            ),
            high_price=cls._decimal(
                payload.get("high_price")
            ),
            low_price=cls._decimal(
                payload.get("low_price")
            ),
            previous_close_price=cls._decimal(
                payload.get("prev_closing_price")
            ),
            change_price=cls._decimal(
                payload.get("signed_change_price")
            ),
            change_rate=cls._decimal(
                payload.get("signed_change_rate")
            ),
            accumulated_volume=cls._decimal(
                payload.get("acc_trade_volume_24h")
                or payload.get("acc_trade_volume")
            ),
            trade_volume=cls._decimal(
                payload.get("trade_volume")
            ),
            event_time=event_time,
            received_at=datetime.now(timezone.utc),
            source_code="UPBIT_WEBSOCKET",
        )
