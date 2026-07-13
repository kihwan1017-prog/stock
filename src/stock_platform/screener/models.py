from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CandidateInput:
    exchange_code: str
    symbol: str
    trade_date: date
    close_price: Decimal
    volume: Decimal
    volume_ma20: Decimal | None
    ma5: Decimal | None
    ma20: Decimal | None
    ma60: Decimal | None
    rsi14: Decimal | None
    macd: Decimal | None
    macd_signal: Decimal | None
    atr14: Decimal | None
    previous_60_high: Decimal | None


@dataclass(frozen=True, slots=True)
class RuleResult:
    volume_surge: bool
    trend_alignment: bool
    rsi_range: bool
    macd_positive: bool
    breakout: bool
    atr_acceptable: bool

    @property
    def passed_count(self) -> int:
        return sum(
            (
                self.volume_surge,
                self.trend_alignment,
                self.rsi_range,
                self.macd_positive,
                self.breakout,
                self.atr_acceptable,
            )
        )

    @property
    def passed(self) -> bool:
        return self.passed_count == 6


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    volume: Decimal
    trend: Decimal
    rsi: Decimal
    macd: Decimal
    breakout: Decimal
    volatility: Decimal

    @property
    def total(self) -> Decimal:
        return (
            self.volume
            + self.trend
            + self.rsi
            + self.macd
            + self.breakout
            + self.volatility
        )


@dataclass(frozen=True, slots=True)
class CandidateScore:
    exchange_code: str
    symbol: str
    trade_date: date
    total_score: Decimal
    rules: RuleResult
    breakdown: ScoreBreakdown
