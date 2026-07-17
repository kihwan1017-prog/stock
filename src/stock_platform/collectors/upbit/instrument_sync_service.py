from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from stock_platform.brokers.upbit.client import UpbitQuotationClient
from stock_platform.markets.service import InstrumentService


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class UpbitInstrumentSyncResult:
    exchange_code: str
    requested_count: int
    saved_count: int
    krw_only: bool


class UpbitInstrumentSyncService:
    """업비트 마켓 목록을 market.instrument에 Upsert한다."""

    def __init__(
        self,
        client: UpbitQuotationClient,
        instrument_service: InstrumentService,
    ) -> None:
        self._client = client
        self._instrument_service = instrument_service

    async def sync(
        self,
        *,
        krw_only: bool = True,
    ) -> UpbitInstrumentSyncResult:
        markets = await self._client.list_markets(is_details=True)

        if krw_only:
            markets = [
                item
                for item in markets
                if str(item.get("market", "")).upper().startswith(
                    "KRW-"
                )
            ]

        rows = [
            self._to_instrument_row(item)
            for item in markets
            if str(item.get("market", "")).strip()
        ]

        saved_count = self._instrument_service.upsert_many(rows)

        logger.info(
            "upbit_instrument_sync_completed",
            krw_only=krw_only,
            requested_count=len(rows),
            saved_count=saved_count,
        )

        return UpbitInstrumentSyncResult(
            exchange_code="UPBIT",
            requested_count=len(rows),
            saved_count=saved_count,
            krw_only=krw_only,
        )

    @staticmethod
    def _to_instrument_row(item: dict[str, Any]) -> dict[str, Any]:
        market = str(item.get("market", "")).strip().upper()
        korean_name = str(
            item.get("korean_name")
            or item.get("english_name")
            or market
        ).strip()

        return {
            "asset_type": "CRYPTO",
            "exchange_code": "UPBIT",
            "symbol": market,
            "name": korean_name,
            "currency_code": "KRW",
            "is_active": True,
            "extra_data": {
                "english_name": item.get("english_name"),
                "market_warning": item.get("market_warning"),
                "market_event": item.get("market_event"),
            },
        }
