from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.markets.models import PriceDaily
from stock_platform.markets.repository import InstrumentRepository
from stock_platform.operation.calendar_repository import TradingCalendarRepository
from stock_platform.operation.calendar_service import TradingCalendarService


@dataclass(frozen=True, slots=True)
class DailyGapRow:
    symbol: str
    expected_date: date
    exists: bool
    gap_reason: str
    repair_status: str


class MarketDataGapDetectionService:
    """누락 일봉 탐지 — UPBIT 달력일, KRX 거래일 기준."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._instruments = InstrumentRepository(session)
        self._calendar = TradingCalendarService(TradingCalendarRepository(session))

    def detect_daily_gaps(
        self,
        *,
        exchange_code: str,
        start_date: date,
        end_date: date,
        symbol_limit: int = 50,
        max_gaps_per_symbol: int = 30,
    ) -> list[dict]:
        exchange = exchange_code.strip().upper()
        expected_dates = self._expected_dates(exchange, start_date, end_date)
        if not expected_dates:
            return []

        instruments = self._instruments.list(
            exchange_code=exchange,
            active_only=True,
            limit=symbol_limit,
        )

        gaps: list[dict] = []
        for instrument in instruments:
            existing = self._session.scalars(
                select(PriceDaily.trade_date).where(
                    PriceDaily.instrument_id == instrument.instrument_id,
                    PriceDaily.trade_date >= start_date,
                    PriceDaily.trade_date <= end_date,
                )
            ).all()
            existing_set = set(existing)
            symbol_gaps = 0
            for expected in expected_dates:
                if symbol_gaps >= max_gaps_per_symbol:
                    break
                if expected in existing_set:
                    continue
                gaps.append(
                    asdict(
                        DailyGapRow(
                            symbol=instrument.symbol,
                            expected_date=expected,
                            exists=False,
                            gap_reason=(
                                "MISSING_TRADING_DAY"
                                if exchange == "KRX"
                                else "MISSING_CALENDAR_DAY"
                            ),
                            repair_status="PENDING",
                        )
                    )
                )
                symbol_gaps += 1
        return gaps

    def _expected_dates(
        self,
        exchange_code: str,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        dates: list[date] = []
        probe = start_date
        while probe <= end_date:
            if exchange_code == "UPBIT":
                dates.append(probe)
            elif self._calendar.is_trading_day("KRX", probe):
                dates.append(probe)
            probe += timedelta(days=1)
        return dates
