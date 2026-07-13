from __future__ import annotations

from decimal import Decimal

from stock_platform.screener.models import CandidateInput, RuleResult


class CandidateRuleEngine:
    """후보 종목의 필수 통과 규칙을 평가한다."""

    def __init__(
        self,
        *,
        minimum_volume_ratio: Decimal = Decimal("2.0"),
        minimum_rsi: Decimal = Decimal("40"),
        maximum_rsi: Decimal = Decimal("70"),
        maximum_atr_ratio: Decimal = Decimal("8"),
    ) -> None:
        self._minimum_volume_ratio = minimum_volume_ratio
        self._minimum_rsi = minimum_rsi
        self._maximum_rsi = maximum_rsi
        self._maximum_atr_ratio = maximum_atr_ratio

    def evaluate(self, item: CandidateInput) -> RuleResult:
        volume_surge = (
            item.volume_ma20 is not None
            and item.volume_ma20 > 0
            and item.volume / item.volume_ma20
            >= self._minimum_volume_ratio
        )

        trend_alignment = (
            item.ma5 is not None
            and item.ma20 is not None
            and item.ma60 is not None
            and item.ma5 > item.ma20 > item.ma60
        )

        rsi_range = (
            item.rsi14 is not None
            and self._minimum_rsi
            <= item.rsi14
            <= self._maximum_rsi
        )

        macd_positive = (
            item.macd is not None
            and item.macd_signal is not None
            and item.macd > item.macd_signal
        )

        breakout = (
            item.previous_60_high is not None
            and item.close_price >= item.previous_60_high
        )

        atr_ratio = (
            item.atr14 / item.close_price * Decimal("100")
            if item.atr14 is not None and item.close_price > 0
            else None
        )

        atr_acceptable = (
            atr_ratio is not None
            and atr_ratio <= self._maximum_atr_ratio
        )

        return RuleResult(
            volume_surge=volume_surge,
            trend_alignment=trend_alignment,
            rsi_range=rsi_range,
            macd_positive=macd_positive,
            breakout=breakout,
            atr_acceptable=atr_acceptable,
        )
