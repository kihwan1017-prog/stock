from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from stock_platform.collectors.upbit.instrument_sync_service import (
    UpbitInstrumentSyncService,
)
from stock_platform.collectors.upbit.sync_service import (
    UpbitDailySyncService,
)
from stock_platform.markets.service import InstrumentService


logger = structlog.get_logger(__name__)

_KST = ZoneInfo("Asia/Seoul")


def today_kst() -> date:
    return datetime.now(_KST).date()


def years_ago(base: date, years: int) -> date:
    """윤년(2/29)을 안전하게 처리한 N년 전 날짜."""

    try:
        return base.replace(year=base.year - years)
    except ValueError:
        return base.replace(
            year=base.year - years,
            month=2,
            day=28,
        )


@dataclass(frozen=True, slots=True)
class UpbitMarketSyncItemResult:
    market: str
    status: str
    collected_count: int = 0
    saved_count: int = 0
    error_message: str | None = None


@dataclass(slots=True)
class UpbitKrwDailyBatchResult:
    exchange_code: str
    start_date: date
    end_date: date
    instrument_synced: int
    market_count: int
    success_count: int
    skipped_count: int
    failed_count: int
    total_collected: int
    total_saved: int
    failed_markets: list[str] = field(default_factory=list)
    items: list[UpbitMarketSyncItemResult] = field(
        default_factory=list
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        return payload


class UpbitKrwDailyBatchSyncService:
    """
    KRW 마켓 전체 일봉 동기화.

    1) 종목 마스터 동기화
    2) 종목별 일봉 수집(기본 3년, resume)
    3) 실패 종목 재시도
    """

    def __init__(
        self,
        instrument_sync: UpbitInstrumentSyncService,
        daily_sync: UpbitDailySyncService,
        instrument_service: InstrumentService,
    ) -> None:
        self._instrument_sync = instrument_sync
        self._daily_sync = daily_sync
        self._instrument_service = instrument_service

    async def sync(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        lookback_years: int = 3,
        resume: bool = True,
        market_limit: int | None = None,
        max_retries: int = 2,
        retry_delay_seconds: float = 1.0,
        sync_instruments: bool = True,
    ) -> UpbitKrwDailyBatchResult:
        if lookback_years <= 0:
            raise ValueError("lookback_years must be > 0")

        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")

        effective_end = end_date or today_kst()
        effective_start = start_date or years_ago(
            effective_end,
            lookback_years,
        )

        if effective_start > effective_end:
            raise ValueError(
                "start_date must not be after end_date"
            )

        instrument_synced = 0
        if sync_instruments:
            instrument_result = await self._instrument_sync.sync(
                krw_only=True
            )
            instrument_synced = instrument_result.saved_count

        markets = [
            item.symbol
            for item in self._instrument_service.list(
                exchange_code="UPBIT",
                active_only=True,
                limit=10_000,
            )
            if item.symbol.upper().startswith("KRW-")
        ]

        if market_limit is not None:
            if market_limit <= 0:
                raise ValueError("market_limit must be > 0")
            markets = markets[:market_limit]

        items: list[UpbitMarketSyncItemResult] = []
        failed_markets: list[str] = []

        for market in markets:
            item = await self._sync_market_with_retry(
                market=market,
                start_date=effective_start,
                end_date=effective_end,
                resume=resume,
                max_retries=max_retries,
                retry_delay_seconds=retry_delay_seconds,
            )
            items.append(item)
            if item.status == "FAILED":
                failed_markets.append(market)

        success_count = sum(
            1 for item in items if item.status == "SUCCESS"
        )
        skipped_count = sum(
            1 for item in items if item.status == "SKIPPED"
        )
        failed_count = len(failed_markets)
        total_collected = sum(
            item.collected_count for item in items
        )
        total_saved = sum(item.saved_count for item in items)

        result = UpbitKrwDailyBatchResult(
            exchange_code="UPBIT",
            start_date=effective_start,
            end_date=effective_end,
            instrument_synced=instrument_synced,
            market_count=len(markets),
            success_count=success_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            total_collected=total_collected,
            total_saved=total_saved,
            failed_markets=failed_markets,
            items=items,
        )

        logger.info(
            "upbit_krw_daily_batch_completed",
            market_count=result.market_count,
            success_count=result.success_count,
            skipped_count=result.skipped_count,
            failed_count=result.failed_count,
            total_saved=result.total_saved,
        )

        if (
            result.market_count > 0
            and result.success_count == 0
            and result.skipped_count == 0
        ):
            raise RuntimeError(
                "Upbit KRW daily batch failed for all markets: "
                + ", ".join(failed_markets[:20])
            )

        return result

    async def _sync_market_with_retry(
        self,
        *,
        market: str,
        start_date: date,
        end_date: date,
        resume: bool,
        max_retries: int,
        retry_delay_seconds: float,
    ) -> UpbitMarketSyncItemResult:
        last_error: str | None = None
        attempts = max_retries + 1

        for attempt in range(1, attempts + 1):
            try:
                sync_result = await self._daily_sync.sync(
                    market=market,
                    start_date=start_date,
                    end_date=end_date,
                    resume=resume,
                )

                if (
                    sync_result.collected_count == 0
                    and sync_result.saved_count == 0
                ):
                    return UpbitMarketSyncItemResult(
                        market=market,
                        status="SKIPPED",
                    )

                return UpbitMarketSyncItemResult(
                    market=market,
                    status="SUCCESS",
                    collected_count=sync_result.collected_count,
                    saved_count=sync_result.saved_count,
                )
            except Exception as exc:
                last_error = str(exc)[:500]
                logger.warning(
                    "upbit_krw_daily_market_failed",
                    market=market,
                    attempt=attempt,
                    max_attempts=attempts,
                    error=last_error,
                )

                if attempt < attempts and retry_delay_seconds > 0:
                    await asyncio.sleep(
                        retry_delay_seconds * attempt
                    )

        return UpbitMarketSyncItemResult(
            market=market,
            status="FAILED",
            error_message=last_error,
        )
