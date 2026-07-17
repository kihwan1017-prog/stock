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
    RealtimeOrderbook,
    RealtimeQuote,
    RealtimeTrade,
)


logger = structlog.get_logger(__name__)

QuoteHandler = Callable[[RealtimeQuote], Awaitable[None]]
TradeHandler = Callable[[RealtimeTrade], Awaitable[None]]
OrderbookHandler = Callable[[RealtimeOrderbook], Awaitable[None]]

_ALLOWED_CHANNELS = frozenset({"ticker", "trade", "orderbook"})


class UpbitRealtimeClient:
    """
    업비트 공개 WebSocket 스트림 클라이언트.

    ticker / trade / orderbook 채널을 구독하고,
    연결이 끊기면 지수 백오프로 자동 재연결한다.
    """

    def __init__(
        self,
        *,
        symbols: list[str],
        quote_handler: QuoteHandler | None = None,
        trade_handler: TradeHandler | None = None,
        orderbook_handler: OrderbookHandler | None = None,
        handler: QuoteHandler | None = None,
        channels: list[str] | None = None,
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

        resolved_quote = quote_handler or handler
        channel_set = {
            item.strip().lower()
            for item in (channels or ["ticker"])
            if item.strip()
        }
        if not channel_set:
            channel_set = {"ticker"}
        invalid = channel_set - _ALLOWED_CHANNELS
        if invalid:
            raise ValueError(
                f"unsupported channels: {sorted(invalid)}"
            )

        if "ticker" in channel_set and resolved_quote is None:
            raise ValueError("quote_handler is required for ticker")
        if "trade" in channel_set and trade_handler is None:
            raise ValueError("trade_handler is required for trade")
        if (
            "orderbook" in channel_set
            and orderbook_handler is None
        ):
            raise ValueError(
                "orderbook_handler is required for orderbook"
            )

        self._symbols = normalized
        self._quote_handler = resolved_quote
        self._trade_handler = trade_handler
        self._orderbook_handler = orderbook_handler
        self._channels = sorted(channel_set)
        self._websocket_url = websocket_url
        self._ping_interval_seconds = ping_interval_seconds
        self._reconnect_max_seconds = reconnect_max_seconds
        self._stop_event = asyncio.Event()
        self._connected = False
        self._last_error: str | None = None
        self._received_count = 0
        self._last_received_at: datetime | None = None

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
                except TimeoutError:
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
            request: list[dict[str, Any]] = [
                {"ticket": str(uuid.uuid4())}
            ]
            for channel in self._channels:
                request.append(
                    {
                        "type": channel,
                        "codes": self._symbols,
                        "is_only_realtime": True,
                    }
                )
            request.append({"format": "DEFAULT"})

            await websocket.send(
                json.dumps(request, ensure_ascii=False)
            )
            self._connected = True
            self._last_error = None

            logger.info(
                "upbit_realtime_connected",
                symbols=self._symbols,
                channels=self._channels,
            )

            while not self._stop_event.is_set():
                try:
                    raw_message = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=90,
                    )
                except TimeoutError:
                    await websocket.ping()
                    continue
                except ConnectionClosed:
                    break

                payload = self._decode_message(raw_message)
                await self._dispatch(payload)
                self._received_count += 1
                self._last_received_at = datetime.now(timezone.utc)

        self._connected = False

    async def _dispatch(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type", "")).lower()

        if event_type in ("ticker", ""):
            # type 누락 시 trade_price 있으면 ticker로 취급
            if event_type == "ticker" or "trade_price" in payload:
                if self._quote_handler is not None:
                    await self._quote_handler(self._to_quote(payload))
                return

        if event_type == "trade" and self._trade_handler is not None:
            await self._trade_handler(self._to_trade(payload))
            return

        if (
            event_type == "orderbook"
            and self._orderbook_handler is not None
        ):
            await self._orderbook_handler(self._to_orderbook(payload))
            return

        logger.debug(
            "upbit_realtime_ignored_payload",
            event_type=event_type,
        )

    async def stop(self) -> None:
        self._stop_event.set()

    def status(self) -> dict[str, Any]:
        return {
            "exchange_code": "UPBIT",
            "connected": self._connected,
            "symbols": self._symbols,
            "channels": self._channels,
            "received_count": self._received_count,
            "last_received_at": (
                self._last_received_at.isoformat()
                if self._last_received_at
                else None
            ),
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
    def _decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    @classmethod
    def _event_time(cls, payload: dict[str, Any]) -> datetime:
        timestamp_value = payload.get("timestamp")
        if timestamp_value is None:
            return datetime.now(timezone.utc)
        return datetime.fromtimestamp(
            int(timestamp_value) / 1000,
            tz=timezone.utc,
        )

    @classmethod
    def _symbol(cls, payload: dict[str, Any]) -> str:
        symbol = str(
            payload.get("code") or payload.get("market") or ""
        ).upper()
        if not symbol:
            raise ValueError("Upbit payload has no code")
        return symbol

    @classmethod
    def _to_quote(cls, payload: dict[str, Any]) -> RealtimeQuote:
        return RealtimeQuote(
            exchange_code="UPBIT",
            symbol=cls._symbol(payload),
            event_type=MarketEventType.TICKER,
            trade_price=Decimal(str(payload["trade_price"])),
            opening_price=cls._decimal(payload.get("opening_price")),
            high_price=cls._decimal(payload.get("high_price")),
            low_price=cls._decimal(payload.get("low_price")),
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
            trade_volume=cls._decimal(payload.get("trade_volume")),
            event_time=cls._event_time(payload),
            received_at=datetime.now(timezone.utc),
            source_code="UPBIT_WEBSOCKET",
        )

    @classmethod
    def _to_trade(cls, payload: dict[str, Any]) -> RealtimeTrade:
        trade_id = str(
            payload.get("sequential_id")
            or payload.get("trade_uuid")
            or ""
        ).strip()
        if not trade_id:
            # 고유키 없으면 시각+가격+수량으로 합성
            trade_id = (
                f"{payload.get('timestamp')}:"
                f"{payload.get('trade_price')}:"
                f"{payload.get('trade_volume')}"
            )

        ask_bid = str(payload.get("ask_bid", "")).upper()
        side = None
        if ask_bid == "ASK":
            side = "SELL"
        elif ask_bid == "BID":
            side = "BUY"

        return RealtimeTrade(
            exchange_code="UPBIT",
            symbol=cls._symbol(payload),
            trade_id=trade_id,
            price=Decimal(str(payload["trade_price"])),
            quantity=Decimal(str(payload["trade_volume"])),
            side=side,
            traded_at=cls._event_time(payload),
            received_at=datetime.now(timezone.utc),
            source_code="UPBIT_WEBSOCKET",
        )

    @classmethod
    def _to_orderbook(
        cls,
        payload: dict[str, Any],
    ) -> RealtimeOrderbook:
        units = payload.get("orderbook_units") or []
        bids: list[dict[str, Any]] = []
        asks: list[dict[str, Any]] = []

        for unit in units:
            if not isinstance(unit, dict):
                continue
            bid_price = unit.get("bid_price")
            bid_size = unit.get("bid_size")
            ask_price = unit.get("ask_price")
            ask_size = unit.get("ask_size")
            if bid_price is not None and bid_size is not None:
                bids.append(
                    {
                        "price": str(bid_price),
                        "quantity": str(bid_size),
                    }
                )
            if ask_price is not None and ask_size is not None:
                asks.append(
                    {
                        "price": str(ask_price),
                        "quantity": str(ask_size),
                    }
                )

        return RealtimeOrderbook(
            exchange_code="UPBIT",
            symbol=cls._symbol(payload),
            bids=bids,
            asks=asks,
            captured_at=cls._event_time(payload),
            received_at=datetime.now(timezone.utc),
            source_code="UPBIT_WEBSOCKET",
        )
