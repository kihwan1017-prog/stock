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
    """
    후보 종목 100점 만점 평가.

    liquidity 10 + trade_value 10 + volume 15 + trend 15
    + rsi 10 + macd 10 + week52 15 + breakout 5 + volatility 10 = 100
    """

    def __init__(
        self,
        rule_engine: CandidateRuleEngine | None = None,
    ) -> None:
        self._rule_engine = rule_engine or CandidateRuleEngine()

    def score(self, item: CandidateInput) -> CandidateScore:
        rules = self._rule_engine.evaluate(item)

        breakdown = ScoreBreakdown(
            liquidity=self._liquidity_score(item),
            trade_value=self._trade_value_score(item),
            volume=self._volume_score(item),
            trend=self._trend_score(item),
            rsi=self._rsi_score(item),
            macd=self._macd_score(item),
            week52=self._week52_score(item),
            breakout=self._breakout_score(item),
            volatility=self._volatility_score(item),
        )

        # 거래정지·관리종목은 총점 0
        total = breakdown.total
        if not rules.tradable:
            total = ZERO

        return CandidateScore(
            exchange_code=item.exchange_code,
            symbol=item.symbol,
            trade_date=item.trade_date,
            total_score=total.quantize(Decimal("0.01")),
            rules=rules,
            breakdown=breakdown,
        )

    @staticmethod
    def _liquidity_score(item: CandidateInput) -> Decimal:
        value = item.trade_value_ma20
        if value is None and item.volume_ma20 is not None:
            value = item.volume_ma20 * item.close_price
        if value is None or value <= 0:
            return ZERO

        # 5억=5점, 50억=10점
        score = value / Decimal("1000000000") * Decimal("2")
        return _clamp(score, ZERO, Decimal("10"))

    @staticmethod
    def _trade_value_score(item: CandidateInput) -> Decimal:
        if item.trade_value <= 0:
            return ZERO
        score = item.trade_value / Decimal("500000000") * Decimal("5")
        return _clamp(score, ZERO, Decimal("10"))

    @staticmethod
    def _volume_score(item: CandidateInput) -> Decimal:
        if item.volume_ma20 is None or item.volume_ma20 <= 0:
            return ZERO

        ratio = item.volume / item.volume_ma20
        return _clamp(
            (ratio - Decimal("1")) * Decimal("7.5"),
            ZERO,
            Decimal("15"),
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
            score += Decimal("6")
        if item.ma20 > item.ma60:
            score += Decimal("6")

        spread = (item.ma5 - item.ma60) / item.ma60 * Decimal("100")
        score += _clamp(spread, ZERO, Decimal("3"))
        return _clamp(score, ZERO, Decimal("15"))

    @staticmethod
    def _rsi_score(item: CandidateInput) -> Decimal:
        if item.rsi14 is None:
            return ZERO
        distance = abs(item.rsi14 - Decimal("55"))
        return _clamp(Decimal("10") - distance * Decimal("0.5"), ZERO, Decimal("10"))

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

        normalized = histogram / item.close_price * Decimal("10000")
        return _clamp(normalized, ZERO, Decimal("10"))

    @staticmethod
    def _week52_score(item: CandidateInput) -> Decimal:
        if (
            item.high_52w is None
            or item.low_52w is None
            or item.high_52w <= item.low_52w
        ):
            return ZERO

        span = item.high_52w - item.low_52w
        position = (item.close_price - item.low_52w) / span
        return _clamp(position * Decimal("15"), ZERO, Decimal("15"))

    @staticmethod
    def _breakout_score(item: CandidateInput) -> Decimal:
        if item.previous_60_high is None or item.previous_60_high <= 0:
            return ZERO

        ratio = (
            item.close_price / item.previous_60_high - Decimal("1")
        ) * Decimal("100")
        if ratio < 0:
            return ZERO
        return _clamp(Decimal("3") + ratio * Decimal("2"), ZERO, Decimal("5"))

    @staticmethod
    def _volatility_score(item: CandidateInput) -> Decimal:
        if item.atr14 is None or item.close_price <= 0:
            return ZERO

        atr_ratio = item.atr14 / item.close_price * Decimal("100")
        if atr_ratio > Decimal("8"):
            return ZERO

        ideal = Decimal("3")
        distance = abs(atr_ratio - ideal)
        return _clamp(
            Decimal("10") - distance * Decimal("2"),
            ZERO,
            Decimal("10"),
        )
