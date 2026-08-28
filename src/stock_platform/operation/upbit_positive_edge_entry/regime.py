"""Market regime from as-of features only (no lookahead)."""

from __future__ import annotations

from enum import Enum


class MarketRegime(str, Enum):
    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


def classify_regime(
    *,
    btc_ret_60m_pct: float | None,
    btc_ma_short: float | None,
    btc_ma_long: float | None,
    btc_realized_vol_60m: float | None,
    vol_high_threshold: float,
    vol_low_threshold: float,
    breadth_rising_ratio: float | None = None,
) -> MarketRegime:
    """BTC 추세·변동성 우선. breadth는 보조."""

    # 변동성 우선 태깅 (상호배타 아님 → primary 한 개만 반환)
    if (
        btc_realized_vol_60m is not None
        and btc_realized_vol_60m >= vol_high_threshold
    ):
        return MarketRegime.HIGH_VOLATILITY
    if (
        btc_realized_vol_60m is not None
        and btc_realized_vol_60m <= vol_low_threshold
    ):
        # 저변동 + 추세면 추세 우선
        pass

    bullish_ma = (
        btc_ma_short is not None
        and btc_ma_long is not None
        and btc_ma_short > btc_ma_long
    )
    bearish_ma = (
        btc_ma_short is not None
        and btc_ma_long is not None
        and btc_ma_short < btc_ma_long
    )
    ret = float(btc_ret_60m_pct) if btc_ret_60m_pct is not None else 0.0

    if bullish_ma and ret >= 0.3:
        return MarketRegime.BULL_TREND
    if bearish_ma and ret <= -0.3:
        return MarketRegime.BEAR_TREND
    if (
        btc_realized_vol_60m is not None
        and btc_realized_vol_60m <= vol_low_threshold
    ):
        return MarketRegime.LOW_VOLATILITY
    if breadth_rising_ratio is not None:
        if breadth_rising_ratio >= 0.62 and ret > 0:
            return MarketRegime.BULL_TREND
        if breadth_rising_ratio <= 0.38 and ret < 0:
            return MarketRegime.BEAR_TREND
    return MarketRegime.SIDEWAYS
