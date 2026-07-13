from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from stock_platform.indicators.engine import IndicatorEngine
from stock_platform.indicators.models import PriceBar
from stock_platform.markets.service import PriceDailyService
from stock_platform.screener.models import (
    CandidateInput,
    CandidateScore,
)
from stock_platform.screener.scoring import (
    CandidateScoringEngine,
)


class CandidateService:
    """일봉과 기술적 지표로 단일 종목 후보 점수를 계산한다."""

    LOOKBACK_DAYS = 260

    def __init__(
        self,
        price_service: PriceDailyService,
        indicator_engine: IndicatorEngine | None = None,
        scoring_engine: CandidateScoringEngine | None = None,
    ) -> None:
        self._price_service = price_service
        self._indicator_engine = (
            indicator_engine or IndicatorEngine()
        )
        self._scoring_engine = (
            scoring_engine or CandidateScoringEngine()
        )

    def evaluate(
        self,
        *,
        exchange_code: str,
        symbol: str,
        as_of_date: date,
    ) -> CandidateScore:
        start_date = as_of_date - timedelta(
            days=self.LOOKBACK_DAYS
        )

        prices = self._price_service.get_between(
            exchange_code=exchange_code,
            symbol=symbol,
            start_date=start_date,
            end_date=as_of_date,
        )

        if not prices:
            raise ValueError(
                f"No daily prices found for "
                f"{exchange_code}/{symbol}"
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

        indicators = self._indicator_engine.calculate(bars)
        latest = indicators[-1]
        latest_bar = bars[-1]

        previous_bars = bars[:-1][-60:]
        previous_60_high = (
            max(
                bar.high_price
                for bar in previous_bars
            )
            if previous_bars
            else None
        )

        candidate = CandidateInput(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            trade_date=latest.trade_date,
            close_price=latest.close_price,
            volume=latest.volume,
            volume_ma20=latest.volume_ma20,
            ma5=latest.ma5,
            ma20=latest.ma20,
            ma60=latest.ma60,
            rsi14=latest.rsi14,
            macd=latest.macd,
            macd_signal=latest.macd_signal,
            atr14=latest.atr14,
            previous_60_high=previous_60_high,
        )

        return self._scoring_engine.score(candidate)
