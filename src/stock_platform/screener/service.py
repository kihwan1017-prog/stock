from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from stock_platform.indicators.engine import IndicatorEngine
from stock_platform.indicators.models import PriceBar
from stock_platform.markets.models import Instrument
from stock_platform.markets.repository import InstrumentRepository
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
)
from stock_platform.screener.models import CandidateInput, CandidateScore
from stock_platform.screener.scoring import CandidateScoringEngine


class ScreenerService:
    """일봉·지표로 단일 종목 후보 점수를 계산한다."""

    LOOKBACK_DAYS = 420

    def __init__(
        self,
        price_service: PriceDailyService | None = None,
        instrument_repository: InstrumentRepository | None = None,
        scoring_engine: CandidateScoringEngine | None = None,
        indicator_engine: IndicatorEngine | None = None,
    ) -> None:
        self._price_service = price_service
        self._instrument_repository = instrument_repository
        self._scoring = scoring_engine or CandidateScoringEngine()
        self._indicator_engine = indicator_engine or IndicatorEngine()

    @staticmethod
    def filter_candidates(indicators: list) -> list:
        """레거시 IndicatorValue 필터 (STEP34 호환)."""

        return [
            item
            for item in indicators
            if getattr(item, "sma5", None) is not None
            and getattr(item, "sma20", None) is not None
            and getattr(item, "rsi14", None) is not None
            and item.sma5 > item.sma20
            and Decimal("40") <= item.rsi14 <= Decimal("70")
        ]

    def evaluate(
        self,
        *,
        exchange_code: str,
        symbol: str,
        as_of_date: date,
    ) -> CandidateScore:
        if self._price_service is None:
            raise RuntimeError(
                "price_service is required for evaluate()"
            )
        normalized_exchange = exchange_code.strip().upper()
        normalized_symbol = symbol.strip().upper()

        prices = self._price_service.get_between(
            exchange_code=normalized_exchange,
            symbol=normalized_symbol,
            start_date=as_of_date - timedelta(days=self.LOOKBACK_DAYS),
            end_date=as_of_date,
        )

        if not prices:
            raise ValueError(
                f"No price data for {normalized_exchange}/{normalized_symbol}"
            )

        # as_of_date 당일 또는 그 이전 최신 봉
        day_rows = [
            row for row in prices if row.trade_date <= as_of_date
        ]
        if not day_rows:
            raise ValueError(
                f"No price on or before {as_of_date.isoformat()}"
            )

        latest = day_rows[-1]
        bars = [
            PriceBar(
                trade_date=row.trade_date,
                open_price=Decimal(row.open_price),
                high_price=Decimal(row.high_price),
                low_price=Decimal(row.low_price),
                close_price=Decimal(row.close_price),
                volume=Decimal(row.volume),
            )
            for row in day_rows
        ]

        indicators = self._indicator_engine.calculate(bars)
        indicator = indicators[-1]

        # 직전 60거래일 고가(당일 제외)
        prior = bars[:-1]
        previous_60_high = None
        if prior:
            window = prior[-60:]
            previous_60_high = max(bar.high_price for bar in window)

        # 거래대금 20일 평균
        trade_values = [
            Decimal(row.trade_value) for row in day_rows[-20:]
        ]
        trade_value_ma20 = (
            sum(trade_values, Decimal("0")) / Decimal(len(trade_values))
            if trade_values
            else None
        )

        instrument = self._resolve_instrument(
            normalized_exchange,
            normalized_symbol,
        )
        halted, managed, active = self._status_flags(instrument)

        candidate = CandidateInput(
            exchange_code=normalized_exchange,
            symbol=normalized_symbol,
            trade_date=latest.trade_date,
            close_price=Decimal(latest.close_price),
            volume=Decimal(latest.volume),
            trade_value=Decimal(latest.trade_value),
            volume_ma20=indicator.volume_ma20,
            trade_value_ma20=trade_value_ma20,
            ma5=indicator.ma5,
            ma20=indicator.ma20,
            ma60=indicator.ma60,
            rsi14=indicator.rsi14,
            macd=indicator.macd,
            macd_signal=indicator.macd_signal,
            atr14=indicator.atr14,
            previous_60_high=previous_60_high,
            high_52w=indicator.high_52w,
            low_52w=indicator.low_52w,
            is_halted=halted,
            is_managed=managed,
            is_active=active,
        )

        return self._scoring.score(candidate)

    def _resolve_instrument(
        self,
        exchange_code: str,
        symbol: str,
    ) -> Instrument | None:
        if self._instrument_repository is None:
            return None
        return self._instrument_repository.find(exchange_code, symbol)

    @staticmethod
    def _status_flags(
        instrument: Instrument | None,
    ) -> tuple[bool, bool, bool]:
        if instrument is None:
            return False, False, True

        extra = instrument.extra_data or {}
        halted = bool(
            extra.get("is_halted")
            or extra.get("trading_halt")
            or extra.get("halt")
        )
        managed = bool(
            extra.get("is_managed")
            or extra.get("management_stock")
            or extra.get("admin_issue")
        )
        # 이름에 관리/거래정지 키워드가 있으면 보수적으로 제외
        name = (instrument.name or "").upper()
        if "관리" in instrument.name or "거래정지" in instrument.name:
            managed = True
        if "HALT" in name:
            halted = True

        return halted, managed, bool(instrument.is_active)
