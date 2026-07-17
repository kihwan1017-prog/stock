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
    trade_value: Decimal
    volume_ma20: Decimal | None
    trade_value_ma20: Decimal | None
    ma5: Decimal | None
    ma20: Decimal | None
    ma60: Decimal | None
    rsi14: Decimal | None
    macd: Decimal | None
    macd_signal: Decimal | None
    atr14: Decimal | None
    previous_60_high: Decimal | None
    high_52w: Decimal | None
    low_52w: Decimal | None
    is_halted: bool = False
    is_managed: bool = False
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class RuleResult:
    """후보 필수 규칙 통과 여부 + 탈락 사유."""

    liquidity: bool
    trade_value: bool
    volume_surge: bool
    trend_alignment: bool
    rsi_range: bool
    week52_position: bool
    atr_acceptable: bool
    tradable: bool
    # 보조 규칙(점수용, passed 판정에는 포함)
    macd_positive: bool
    breakout: bool
    rejection_reasons: tuple[str, ...] = ()

    @property
    def core_flags(self) -> tuple[bool, ...]:
        return (
            self.liquidity,
            self.trade_value,
            self.volume_surge,
            self.trend_alignment,
            self.rsi_range,
            self.week52_position,
            self.atr_acceptable,
            self.tradable,
        )

    @property
    def passed_count(self) -> int:
        return sum(self.core_flags)

    @property
    def core_rule_count(self) -> int:
        return len(self.core_flags)

    @property
    def passed(self) -> bool:
        return self.passed_count == self.core_rule_count

    def to_dict(self) -> dict:
        return {
            "liquidity": self.liquidity,
            "trade_value": self.trade_value,
            "volume_surge": self.volume_surge,
            "trend_alignment": self.trend_alignment,
            "rsi_range": self.rsi_range,
            "week52_position": self.week52_position,
            "atr_acceptable": self.atr_acceptable,
            "tradable": self.tradable,
            "macd_positive": self.macd_positive,
            "breakout": self.breakout,
            "passed_count": self.passed_count,
            "passed": self.passed,
            "rejection_reasons": list(self.rejection_reasons),
        }


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    liquidity: Decimal
    trade_value: Decimal
    volume: Decimal
    trend: Decimal
    rsi: Decimal
    macd: Decimal
    week52: Decimal
    breakout: Decimal
    volatility: Decimal

    @property
    def total(self) -> Decimal:
        return (
            self.liquidity
            + self.trade_value
            + self.volume
            + self.trend
            + self.rsi
            + self.macd
            + self.week52
            + self.breakout
            + self.volatility
        )

    def to_dict(self) -> dict:
        return {
            "liquidity": str(self.liquidity),
            "trade_value": str(self.trade_value),
            "volume": str(self.volume),
            "trend": str(self.trend),
            "rsi": str(self.rsi),
            "macd": str(self.macd),
            "week52": str(self.week52),
            "breakout": str(self.breakout),
            "volatility": str(self.volatility),
            "total": str(self.total),
        }


@dataclass(frozen=True, slots=True)
class CandidateScore:
    exchange_code: str
    symbol: str
    trade_date: date
    total_score: Decimal
    rules: RuleResult
    breakdown: ScoreBreakdown
