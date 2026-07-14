from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from stock_platform.realtime.models import (
    MarketEventType,
    RealtimeQuote,
)


QuoteHandler = Callable[[RealtimeQuote], Awaitable[None]]


class KrxQuoteProvider(Protocol):
    async def get_current_price(
        self,
        symbol: str,
    ) -> dict:
        """키움 REST 현재가 응답을 정규화한 dict로 반환한다."""


class KrxPollingRealtimeClient:
    """
    키움 REST 현재가 조회 어댑터.

    키움 실시간 WebSocket 적용 전에도 기존 REST 클라이언트를
    Provider로 연결해 짧은 주기 시세 수신이 가능하다.
    """

    def __init__(
        self,
        *,
        symbols: list[str],
        provider: KrxQuoteProvider,
        handler: QuoteHandler,
        interval_seconds: float = 1.0,
    ) -> None:
        if interval_seconds < 0.2:
            raise ValueError(
                "interval_seconds must be at least 0.2"
            )

        self._symbols = sorted(
            {
                symbol.strip().upper()
                for symbol in symbols
                if symbol.strip()
            }
        )
        if not self._symbols:
            raise ValueError("symbols must not be empty")

        self._provider = provider
        self._handler = handler
        self._interval_seconds = interval_seconds
        self._stop_event = asyncio.Event()
        self._running = False
        self._received_count = 0
        self._last_error: str | None = None

    async def run_forever(self) -> None:
        self._running = True

        try:
            while not self._stop_event.is_set():
                started_at = asyncio.get_running_loop().time()

                for symbol in self._symbols:
                    try:
                        payload = await self._provider.get_current_price(
                            symbol
                        )
                        quote = self._to_quote(
                            symbol=symbol,
                            payload=payload,
                        )
                        self._received_count += 1
                        self._last_error = None
                        await self._handler(quote)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self._last_error = str(exc)

                elapsed = (
                    asyncio.get_running_loop().time()
                    - started_at
                )
                wait_seconds = max(
                    self._interval_seconds - elapsed,
                    0,
                )

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=wait_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            self._running = False

    async def stop(self) -> None:
        self._stop_event.set()

    def status(self) -> dict:
        return {
            "exchange_code": "KRX",
            "running": self._running,
            "symbols": self._symbols,
            "received_count": self._received_count,
            "last_error": self._last_error,
            "interval_seconds": self._interval_seconds,
        }

    @staticmethod
    def _optional_decimal(
        payload: dict,
        key: str,
    ) -> Decimal | None:
        value = payload.get(key)
        if value in (None, ""):
            return None
        return Decimal(str(value).replace(",", ""))

    @classmethod
    def _to_quote(
        cls,
        *,
        symbol: str,
        payload: dict,
    ) -> RealtimeQuote:
        price_value = (
            payload.get("trade_price")
            or payload.get("current_price")
            or payload.get("price")
        )
        if price_value in (None, ""):
            raise ValueError(
                "KRX current price payload has no price"
            )

        now = datetime.now(timezone.utc)

        return RealtimeQuote(
            exchange_code="KRX",
            symbol=symbol,
            event_type=MarketEventType.TICKER,
            trade_price=Decimal(
                str(price_value).replace(",", "")
            ),
            opening_price=cls._optional_decimal(
                payload,
                "opening_price",
            ),
            high_price=cls._optional_decimal(
                payload,
                "high_price",
            ),
            low_price=cls._optional_decimal(
                payload,
                "low_price",
            ),
            previous_close_price=cls._optional_decimal(
                payload,
                "previous_close_price",
            ),
            change_price=cls._optional_decimal(
                payload,
                "change_price",
            ),
            change_rate=cls._optional_decimal(
                payload,
                "change_rate",
            ),
            accumulated_volume=cls._optional_decimal(
                payload,
                "accumulated_volume",
            ),
            trade_volume=cls._optional_decimal(
                payload,
                "trade_volume",
            ),
            event_time=now,
            received_at=now,
            source_code="KIWOOM_REST_POLLING",
        )
