from __future__ import annotations

from decimal import Decimal

from stock_platform.screener.models import (
    CandidateInput,
    CandidateScore,
    ScoreBreakdown,
)
from stock_platform.screener.rules import CandidateRuleEngine


ZERO = Decimal("0")


def _clamp(
    value: Decimal,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    return max(minimum, min(maximum, value))


class CandidateScoringEngine:
    """후보 종목을 100점 만점으로 평가한다."""

    def __init__(
        self,
        rule_engine: CandidateRuleEngine | None = None,
    ) -> None:
        self._rule_engine = rule_engine or CandidateRuleEngine()

    def score(self, item: CandidateInput) -> CandidateScore:
        rules = self._rule_engine.evaluate(item)

        breakdown = ScoreBreakdown(
            volume=self._volume_score(item),
            trend=self._trend_score(item),
            rsi=self._rsi_score(item),
            macd=self._macd_score(item),
            breakout=self._breakout_score(item),
            volatility=self._volatility_score(item),
        )

        return CandidateScore(
            exchange_code=item.exchange_code,
            symbol=item.symbol,
            trade_date=item.trade_date,
            total_score=breakdown.total.quantize(
                Decimal("0.01")
            ),
            rules=rules,
            breakdown=breakdown,
        )

    @staticmethod
    def _volume_score(item: CandidateInput) -> Decimal:
        if item.volume_ma20 is None or item.volume_ma20 <= 0:
            return ZERO

        ratio = item.volume / item.volume_ma20
        return _clamp(
            (ratio - Decimal("1")) * Decimal("10"),
            ZERO,
            Decimal("20"),
        )

    @staticmethod
    def _trend_score(item: CandidateInput) -> Decimal:
        if (
            item.ma5 is None
            or item.ma20 is None
            or item.ma60 is None
            or item.ma60 <= 0
        ):
            return ZERO

        score = ZERO

        if item.ma5 > item.ma20:
            score += Decimal("8")

        if item.ma20 > item.ma60:
            score += Decimal("8")

        spread = (
            (item.ma5 - item.ma60)
            / item.ma60
            * Decimal("100")
        )
        score += _clamp(
            spread,
            ZERO,
            Decimal("4"),
        )

        return _clamp(score, ZERO, Decimal("20"))

    @staticmethod
    def _rsi_score(item: CandidateInput) -> Decimal:
        if item.rsi14 is None:
            return ZERO

        distance = abs(item.rsi14 - Decimal("55"))

        return _clamp(
            Decimal("15") - distance,
            ZERO,
            Decimal("15"),
        )

    @staticmethod
    def _macd_score(item: CandidateInput) -> Decimal:
        if (
            item.macd is None
            or item.macd_signal is None
            or item.close_price <= 0
        ):
            return ZERO

        histogram = item.macd - item.macd_signal

        if histogram <= 0:
            return ZERO

        normalized = (
            histogram
            / item.close_price
            * Decimal("10000")
        )

        return _clamp(
            normalized,
            ZERO,
            Decimal("20"),
        )

    @staticmethod
    def _breakout_score(item: CandidateInput) -> Decimal:
        if (
            item.previous_60_high is None
            or item.previous_60_high <= 0
        ):
            return ZERO

        ratio = (
            item.close_price
            / item.previous_60_high
            - Decimal("1")
        ) * Decimal("100")

        if ratio < 0:
            return ZERO

        return _clamp(
            Decimal("10") + ratio * Decimal("5"),
            ZERO,
            Decimal("15"),
        )

    @staticmethod
    def _volatility_score(item: CandidateInput) -> Decimal:
        if item.atr14 is None or item.close_price <= 0:
            return ZERO

        atr_ratio = (
            item.atr14
            / item.close_price
            * Decimal("100")
        )

        if atr_ratio > Decimal("8"):
            return ZERO

        ideal = Decimal("3")
        distance = abs(atr_ratio - ideal)

        return _clamp(
            Decimal("10") - distance * Decimal("2"),
            ZERO,
            Decimal("10"),
        )
