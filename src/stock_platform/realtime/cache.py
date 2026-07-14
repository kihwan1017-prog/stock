from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from stock_platform.realtime.models import RealtimeQuote


class RealtimeQuoteCache:
    """종목별 최신 시세를 메모리에 보관한다."""

    def __init__(self) -> None:
        self._items: dict[str, RealtimeQuote] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(exchange_code: str, symbol: str) -> str:
        return f"{exchange_code.upper()}:{symbol.upper()}"

    async def set(self, quote: RealtimeQuote) -> None:
        async with self._lock:
            self._items[
                self._key(quote.exchange_code, quote.symbol)
            ] = quote

    async def get(
        self,
        *,
        exchange_code: str,
        symbol: str,
    ) -> RealtimeQuote | None:
        async with self._lock:
            return self._items.get(
                self._key(exchange_code, symbol)
            )

    async def list_all(self) -> list[RealtimeQuote]:
        async with self._lock:
            return list(self._items.values())

    async def health(self) -> dict:
        async with self._lock:
            latest = max(
                (
                    item.received_at
                    for item in self._items.values()
                ),
                default=None,
            )

            age_seconds = None
            if latest is not None:
                age_seconds = (
                    datetime.now(timezone.utc) - latest
                ).total_seconds()

            return {
                "symbol_count": len(self._items),
                "latest_received_at": latest,
                "latest_age_seconds": age_seconds,
            }
