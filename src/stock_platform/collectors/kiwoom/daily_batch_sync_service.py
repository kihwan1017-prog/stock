"""기존 KiwoomDailySyncService를 재사용하는 KRX 일봉 배치.

새 daily collector를 만들지 않는다. 심볼 순서는 instrument.symbol ASC.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from stock_platform.collectors.kiwoom.sync_service import (
    KiwoomDailySyncService,
)
from stock_platform.markets.service import InstrumentService


logger = structlog.get_logger(__name__)

_KST = ZoneInfo("Asia/Seoul")
RECOMMENDED_LOOKBACK_BARS = 252
SCREENER_LOOKBACK_DAYS = 420


def today_kst() -> date:
    return datetime.now(_KST).date()


@dataclass(frozen=True, slots=True)
class KiwoomDailyBatchItemResult:
    symbol: str
    status: str
    collected_count: int = 0
    saved_count: int = 0
    error_message: str | None = None


@dataclass(slots=True)
class KiwoomDailyBatchResult:
    exchange_code: str
    start_date: date
    end_date: date
    requested_symbols: int
    completed_symbols: int
    skipped_symbols: int
    failed_symbols: int
    total_collected: int
    total_saved: int
    failed: list[str] = field(default_factory=list)
    items: list[KiwoomDailyBatchItemResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        return payload


class KiwoomDailyBatchSyncService:
    """KRX 활성 종목 일봉을 chunk/rate-limit 으로 수집한다."""

    def __init__(
        self,
        daily_sync: KiwoomDailySyncService,
        instrument_service: InstrumentService,
    ) -> None:
        self._daily_sync = daily_sync
        self._instrument_service = instrument_service

    async def sync(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        lookback_days: int = SCREENER_LOOKBACK_DAYS,
        resume: bool = True,
        symbol_limit: int | None = None,
        batch_size: int = 20,
        delay_seconds: float = 0.2,
        max_retries: int = 2,
        asset_types: tuple[str, ...] = ("STOCK", "ETF"),
    ) -> KiwoomDailyBatchResult:
        if lookback_days <= 0:
            raise ValueError("lookback_days must be > 0")
        if batch_size <= 0:
            raise ValueError("batch_size must be > 0")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")

        effective_end = end_date or today_kst()
        effective_start = start_date or (
            effective_end - timedelta(days=lookback_days)
        )
        if effective_start > effective_end:
            raise ValueError("start_date must not be after end_date")

        allowed_assets = {item.upper() for item in asset_types}
        symbols = [
            item.symbol.strip().upper()
            for item in self._instrument_service.list(
                exchange_code="KRX",
                active_only=True,
                limit=50_000,
            )
            if item.asset_type.upper() in allowed_assets
        ]
        symbols = sorted({item for item in symbols if item})

        if symbol_limit is not None:
            if symbol_limit <= 0:
                raise ValueError("symbol_limit must be > 0")
            symbols = symbols[:symbol_limit]

        items: list[KiwoomDailyBatchItemResult] = []
        failed: list[str] = []

        for index, symbol in enumerate(symbols, start=1):
            item = await self._sync_one(
                symbol=symbol,
                start_date=effective_start,
                end_date=effective_end,
                resume=resume,
                max_retries=max_retries,
                delay_seconds=delay_seconds,
            )
            items.append(item)
            if item.status == "FAILED":
                failed.append(symbol)

            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

            if index % batch_size == 0:
                logger.info(
                    "kiwoom_daily_batch_progress",
                    completed=index,
                    requested=len(symbols),
                    failed=len(failed),
                )

        completed = sum(1 for item in items if item.status == "SUCCESS")
        skipped = sum(1 for item in items if item.status == "SKIPPED")
        result = KiwoomDailyBatchResult(
            exchange_code="KRX",
            start_date=effective_start,
            end_date=effective_end,
            requested_symbols=len(symbols),
            completed_symbols=completed,
            skipped_symbols=skipped,
            failed_symbols=len(failed),
            total_collected=sum(item.collected_count for item in items),
            total_saved=sum(item.saved_count for item in items),
            failed=failed,
            items=items,
        )
        logger.info("kiwoom_daily_batch_completed", **result.to_dict())
        return result

    async def _sync_one(
        self,
        *,
        symbol: str,
        start_date: date,
        end_date: date,
        resume: bool,
        max_retries: int,
        delay_seconds: float,
    ) -> KiwoomDailyBatchItemResult:
        last_error: str | None = None
        for attempt in range(max_retries + 1):
            try:
                synced = await self._daily_sync.sync(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    exchange_code="KRX",
                    resume=resume,
                )
                status = (
                    "SKIPPED"
                    if synced.collected_count == 0 and synced.saved_count == 0
                    else "SUCCESS"
                )
                return KiwoomDailyBatchItemResult(
                    symbol=symbol,
                    status=status,
                    collected_count=synced.collected_count,
                    saved_count=synced.saved_count,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"[:240]
                logger.warning(
                    "kiwoom_daily_batch_symbol_failed",
                    symbol=symbol,
                    attempt=attempt + 1,
                    error=last_error,
                )
                if attempt < max_retries and delay_seconds > 0:
                    await asyncio.sleep(delay_seconds * (attempt + 1))

        return KiwoomDailyBatchItemResult(
            symbol=symbol,
            status="FAILED",
            error_message=last_error,
        )
