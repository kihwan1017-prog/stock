"""키움 종목 마스터를 market.instrument 에 idempotent upsert 한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from stock_platform.collectors.kiwoom.instrument_collector import (
    DEFAULT_MARKET_TYPES,
    KiwoomInstrumentCollector,
    KiwoomInstrumentDTO,
)
from stock_platform.markets.service import InstrumentService


logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class KiwoomInstrumentSyncResult:
    exchange_code: str
    requested: int
    received: int
    inserted: int
    updated: int
    skipped: int
    failed: int
    kospi: int = 0
    kosdaq: int = 0
    etf: int = 0
    etn: int = 0
    other: int = 0
    market_types: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "exchange_code": self.exchange_code,
            "requested": self.requested,
            "received": self.received,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "failed": self.failed,
            "kospi": self.kospi,
            "kosdaq": self.kosdaq,
            "etf": self.etf,
            "etn": self.etn,
            "other": self.other,
            "market_types": list(self.market_types),
        }


class KiwoomInstrumentSyncService:
    """UpbitInstrumentSyncService 패턴. hard delete 없음."""

    def __init__(
        self,
        collector: KiwoomInstrumentCollector,
        instrument_service: InstrumentService,
    ) -> None:
        self._collector = collector
        self._instrument_service = instrument_service

    async def sync(
        self,
        *,
        market_types: tuple[str, ...] | list[str] | None = None,
        max_pages: int = 100,
    ) -> KiwoomInstrumentSyncResult:
        requested_types = tuple(market_types or DEFAULT_MARKET_TYPES)
        raw_rows = await self._collector.collect(
            market_types=requested_types,
            max_pages=max_pages,
        )
        unique_rows = _dedupe_by_symbol(raw_rows)
        skipped = len(raw_rows) - len(unique_rows)

        existing = {
            item.symbol.strip().upper(): item
            for item in self._instrument_service.list(
                exchange_code="KRX",
                active_only=False,
                limit=50_000,
            )
        }

        payload = [_to_instrument_row(item) for item in unique_rows]
        inserted = 0
        updated = 0
        failed = 0

        if payload:
            try:
                self._instrument_service.upsert_many(payload)
            except Exception:
                logger.exception("kiwoom_instrument_upsert_failed")
                failed = len(payload)
                payload = []

        if payload:
            for item in unique_rows:
                if item.symbol in existing:
                    updated += 1
                else:
                    inserted += 1

        counts = _segment_counts(unique_rows)
        result = KiwoomInstrumentSyncResult(
            exchange_code="KRX",
            requested=len(requested_types),
            received=len(raw_rows),
            inserted=inserted,
            updated=updated,
            skipped=skipped,
            failed=failed,
            kospi=counts["KOSPI"],
            kosdaq=counts["KOSDAQ"],
            etf=counts["ETF"],
            etn=counts["ETN"],
            other=counts["OTHER"],
            market_types=requested_types,
        )
        logger.info(
            "kiwoom_instrument_sync_completed",
            **result.to_dict(),
        )
        return result


def _dedupe_by_symbol(
    rows: list[KiwoomInstrumentDTO],
) -> list[KiwoomInstrumentDTO]:
    """같은 symbol은 먼저 나온 시장을 유지한다 (KOSPI 우선 호출 가정)."""

    unique: dict[str, KiwoomInstrumentDTO] = {}
    for row in rows:
        if row.symbol not in unique:
            unique[row.symbol] = row
    return list(unique.values())


def _to_instrument_row(item: KiwoomInstrumentDTO) -> dict[str, Any]:
    return {
        "asset_type": item.asset_type,
        "exchange_code": item.exchange_code,
        "symbol": item.symbol,
        "name": item.name,
        "currency_code": "KRW",
        "listed_date": item.listed_date,
        "is_active": item.is_active,
        "extra_data": item.extra_data,
    }


def _segment_counts(rows: list[KiwoomInstrumentDTO]) -> dict[str, int]:
    counts = {
        "KOSPI": 0,
        "KOSDAQ": 0,
        "ETF": 0,
        "ETN": 0,
        "OTHER": 0,
    }
    for row in rows:
        if row.is_etn:
            counts["ETN"] += 1
        elif row.is_etf:
            counts["ETF"] += 1
        elif row.market_segment == "KOSPI":
            counts["KOSPI"] += 1
        elif row.market_segment == "KOSDAQ":
            counts["KOSDAQ"] += 1
        else:
            counts["OTHER"] += 1
    return counts
