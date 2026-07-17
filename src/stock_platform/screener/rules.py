from __future__ import annotations

from decimal import Decimal

from stock_platform.screener.models import CandidateInput, RuleResult


class CandidateRuleEngine:
    """
    후보 종목 필수 규칙 평가.

    핵심 규칙(8):
    - liquidity / trade_value / volume_surge / trend
    - rsi / week52_position / atr / tradable
    """

    def __init__(
        self,
        *,
        minimum_volume_ratio: Decimal = Decimal("2.0"),
        minimum_rsi: Decimal = Decimal("40"),
        maximum_rsi: Decimal = Decimal("70"),
        maximum_atr_ratio: Decimal = Decimal("8"),
        minimum_trade_value: Decimal = Decimal("100000000"),
        minimum_liquidity_value: Decimal = Decimal("500000000"),
        week52_min_position: Decimal = Decimal("0.50"),
    ) -> None:
        self._minimum_volume_ratio = minimum_volume_ratio
        self._minimum_rsi = minimum_rsi
        self._maximum_rsi = maximum_rsi
        self._maximum_atr_ratio = maximum_atr_ratio
        self._minimum_trade_value = minimum_trade_value
        self._minimum_liquidity_value = minimum_liquidity_value
        self._week52_min_position = week52_min_position

    def evaluate(self, item: CandidateInput) -> RuleResult:
        reasons: list[str] = []

        tradable = (
            item.is_active
            and not item.is_halted
            and not item.is_managed
        )
        if not item.is_active:
            reasons.append("inactive_instrument")
        if item.is_halted:
            reasons.append("trading_halted")
        if item.is_managed:
            reasons.append("managed_stock")

        # 유동성: 20일 평균 거래대금 또는 volume_ma20 * close
        liquidity_value = item.trade_value_ma20
        if liquidity_value is None and item.volume_ma20 is not None:
            liquidity_value = item.volume_ma20 * item.close_price

        liquidity = (
            liquidity_value is not None
            and liquidity_value >= self._minimum_liquidity_value
        )
        if not liquidity:
            reasons.append("insufficient_liquidity")

        trade_value_ok = item.trade_value >= self._minimum_trade_value
        if not trade_value_ok:
            reasons.append("insufficient_trade_value")

        volume_surge = (
            item.volume_ma20 is not None
            and item.volume_ma20 > 0
            and item.volume / item.volume_ma20
            >= self._minimum_volume_ratio
        )
        if not volume_surge:
            reasons.append("volume_surge_not_met")

        trend_alignment = (
            item.ma5 is not None
            and item.ma20 is not None
            and item.ma60 is not None
            and item.ma5 > item.ma20 > item.ma60
        )
        if not trend_alignment:
            reasons.append("trend_not_aligned")

        rsi_range = (
            item.rsi14 is not None
            and self._minimum_rsi <= item.rsi14 <= self._maximum_rsi
        )
        if not rsi_range:
            reasons.append("rsi_out_of_range")

        week52_position = self._week52_ok(item)
        if not week52_position:
            reasons.append("week52_position_too_low")

        atr_ratio = (
            item.atr14 / item.close_price * Decimal("100")
            if item.atr14 is not None and item.close_price > 0
            else None
        )
        atr_acceptable = (
            atr_ratio is not None
            and atr_ratio <= self._maximum_atr_ratio
        )
        if not atr_acceptable:
            reasons.append("excessive_volatility")

        macd_positive = (
            item.macd is not None
            and item.macd_signal is not None
            and item.macd > item.macd_signal
        )

        breakout = (
            item.previous_60_high is not None
            and item.close_price >= item.previous_60_high
        )

        return RuleResult(
            liquidity=liquidity,
            trade_value=trade_value_ok,
            volume_surge=volume_surge,
            trend_alignment=trend_alignment,
            rsi_range=rsi_range,
            week52_position=week52_position,
            atr_acceptable=atr_acceptable,
            tradable=tradable,
            macd_positive=macd_positive,
            breakout=breakout,
            rejection_reasons=tuple(reasons),
        )

    def _week52_ok(self, item: CandidateInput) -> bool:
        """52주 밴드 상단 근처(기본 50% 이상)에 위치해야 통과."""

        if (
            item.high_52w is None
            or item.low_52w is None
            or item.high_52w <= item.low_52w
        ):
            return False

        span = item.high_52w - item.low_52w
        position = (item.close_price - item.low_52w) / span
        return position >= self._week52_min_position
