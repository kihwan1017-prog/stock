from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from stock_platform.indicators.engine import IndicatorEngine
from stock_platform.indicators.models import DailyIndicator, PriceBar
from stock_platform.markets.service import PriceDailyService


class IndicatorService:
    """DB 일봉을 조회해 기술적 지표를 계산한다."""

    WARMUP_DAYS = 180

    def __init__(
        self,
        price_service: PriceDailyService,
        engine: IndicatorEngine | None = None,
    ) -> None:
        self._price_service = price_service
        self._engine = engine or IndicatorEngine()

    def calculate_daily(
        self,
        *,
        exchange_code: str,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[DailyIndicator]:
        if start_date > end_date:
            raise ValueError(
                "start_date must not be after end_date"
            )

        warmup_start = (
            start_date - timedelta(days=self.WARMUP_DAYS)
        )

        prices = self._price_service.get_between(
            exchange_code=exchange_code,
            symbol=symbol,
            start_date=warmup_start,
            end_date=end_date,
        )

        bars = [
            PriceBar(
                trade_date=item.trade_date,
                open_price=Decimal(item.open_price),
                high_price=Decimal(item.high_price),
                low_price=Decimal(item.low_price),
                close_price=Decimal(item.close_price),
                volume=Decimal(item.volume),
            )
            for item in prices
        ]

        indicators = self._engine.calculate(bars)

        return [
            item
            for item in indicators
            if start_date <= item.trade_date <= end_date
        ]
