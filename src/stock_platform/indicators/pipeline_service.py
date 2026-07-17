from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import structlog

from stock_platform.indicators.engine import IndicatorEngine
from stock_platform.indicators.models import DailyIndicator
from stock_platform.indicators.repository import (
    IndicatorDailyRepository,
)
from stock_platform.indicators.service import IndicatorService
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    InstrumentService,
    PriceDailyService,
)


logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class IndicatorComputeResult:
    exchange_code: str
    symbol: str
    start_date: date
    end_date: date
    computed_count: int
    saved_count: int
    ready_count: int
    partial_count: int
    insufficient_count: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        return payload


@dataclass(slots=True)
class IndicatorBatchResult:
    exchange_code: str | None
    start_date: date
    end_date: date
    instrument_count: int
    success_count: int
    failed_count: int
    total_saved: int
    failed_symbols: list[str] = field(default_factory=list)
    items: list[IndicatorComputeResult] = field(
        default_factory=list
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "exchange_code": self.exchange_code,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "instrument_count": self.instrument_count,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "total_saved": self.total_saved,
            "failed_symbols": self.failed_symbols,
            "items": [item.to_dict() for item in self.items],
        }


class IndicatorPipelineService:
    """지표 계산 후 market.indicator_daily에 Upsert한다."""

    def __init__(
        self,
        price_service: PriceDailyService,
        indicator_repository: IndicatorDailyRepository,
        instrument_service: InstrumentService,
        engine: IndicatorEngine | None = None,
    ) -> None:
        self._calculator = IndicatorService(
            price_service,
            engine=engine,
        )
        self._repository = indicator_repository
        self._instrument_service = instrument_service

    def compute_and_save(
        self,
        *,
        exchange_code: str,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> IndicatorComputeResult:
        instrument = self._instrument_service.get(
            exchange_code,
            symbol,
        )
        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument not found: {exchange_code}/{symbol}"
            )

        indicators = self._calculator.calculate_daily(
            exchange_code=exchange_code,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )

        now = datetime.now(timezone.utc)
        rows = [
            self._to_row(instrument.instrument_id, item, now)
            for item in indicators
        ]
        saved_count = self._repository.upsert_many(rows)

        return IndicatorComputeResult(
            exchange_code=exchange_code,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            computed_count=len(indicators),
            saved_count=saved_count,
            ready_count=sum(
                1 for item in indicators if item.status_code == "READY"
            ),
            partial_count=sum(
                1
                for item in indicators
                if item.status_code == "PARTIAL"
            ),
            insufficient_count=sum(
                1
                for item in indicators
                if item.status_code == "INSUFFICIENT"
            ),
        )

    def compute_batch(
        self,
        *,
        start_date: date,
        end_date: date,
        exchange_code: str | None = None,
        symbol_limit: int | None = None,
    ) -> IndicatorBatchResult:
        instruments = self._instrument_service.list(
            exchange_code=exchange_code,
            active_only=True,
            limit=symbol_limit or 10_000,
        )
        if symbol_limit is not None:
            instruments = instruments[:symbol_limit]

        items: list[IndicatorComputeResult] = []
        failed_symbols: list[str] = []
        total_saved = 0

        for instrument in instruments:
            try:
                result = self.compute_and_save(
                    exchange_code=instrument.exchange_code,
                    symbol=instrument.symbol,
                    start_date=start_date,
                    end_date=end_date,
                )
                items.append(result)
                total_saved += result.saved_count
            except Exception as exc:
                failed_symbols.append(instrument.symbol)
                logger.warning(
                    "indicator_batch_symbol_failed",
                    exchange_code=instrument.exchange_code,
                    symbol=instrument.symbol,
                    error=str(exc)[:500],
                )

        return IndicatorBatchResult(
            exchange_code=exchange_code,
            start_date=start_date,
            end_date=end_date,
            instrument_count=len(instruments),
            success_count=len(items),
            failed_count=len(failed_symbols),
            total_saved=total_saved,
            failed_symbols=failed_symbols,
            items=items,
        )

    def list_saved(
        self,
        *,
        exchange_code: str,
        symbol: str,
        start_date: date,
        end_date: date,
    ):
        instrument = self._instrument_service.get(
            exchange_code,
            symbol,
        )
        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument not found: {exchange_code}/{symbol}"
            )
        return self._repository.list_between(
            instrument.instrument_id,
            start_date,
            end_date,
        )

    @staticmethod
    def _to_row(
        instrument_id: int,
        item: DailyIndicator,
        now: datetime,
    ) -> dict[str, Any]:
        return {
            "instrument_id": instrument_id,
            "trade_date": item.trade_date,
            "close_price": item.close_price,
            "volume": item.volume,
            "ma5": item.ma5,
            "ma20": item.ma20,
            "ma60": item.ma60,
            "ema12": item.ema12,
            "ema26": item.ema26,
            "rsi14": item.rsi14,
            "macd": item.macd,
            "macd_signal": item.macd_signal,
            "macd_histogram": item.macd_histogram,
            "bollinger_middle": item.bollinger_middle,
            "bollinger_upper": item.bollinger_upper,
            "bollinger_lower": item.bollinger_lower,
            "atr14": item.atr14,
            "volume_ma20": item.volume_ma20,
            "high_52w": item.high_52w,
            "low_52w": item.low_52w,
            "status_code": item.status_code,
            "missing_fields": list(item.missing_fields),
            "updated_at": now,
        }
