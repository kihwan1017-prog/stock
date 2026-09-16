"""1m candle 기반 기술지표 — 기존 indicators.engine helper 재사용.

방향성(BUY/SELL) 라벨은 넣지 않고 수치만 제공한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from stock_platform.ai.market_analysis.candle import decimal_str, to_decimal
from stock_platform.indicators.engine import (
    _atr_wilder,
    _ema,
    _macd,
    _rolling_mean,
    _rsi_wilder,
    _stddev_population,
)
from stock_platform.indicators.models import PriceBar

ZERO = Decimal("0")


def compute_minute_chart_indicators(
    candles: list[dict[str, Any]],
) -> dict[str, Any]:
    """최근 완성 분봉으로 MA/RSI/MACD/ATR·수익률·변동성 수치 계산."""

    if len(candles) < 5:
        return {"status": "INSUFFICIENT", "candle_count": len(candles)}

    closes: list[Decimal] = []
    volumes: list[Decimal] = []
    bars: list[PriceBar] = []
    base = date(2000, 1, 1)
    for index, candle in enumerate(candles):
        try:
            close = to_decimal(candle["close"])
            high = to_decimal(candle["high"])
            low = to_decimal(candle["low"])
            open_ = to_decimal(candle["open"])
            volume = to_decimal(candle.get("volume") or 0)
        except (KeyError, ValueError, TypeError):
            continue
        closes.append(close)
        volumes.append(volume)
        bars.append(
            PriceBar(
                trade_date=base + timedelta(days=index),
                open_price=open_,
                high_price=high,
                low_price=low,
                close_price=close,
                volume=volume,
            )
        )

    if len(closes) < 5:
        return {"status": "INSUFFICIENT", "candle_count": len(closes)}

    last = len(closes) - 1
    ma5_series = _rolling_mean(closes, 5)
    ma20_series = (
        _rolling_mean(closes, 20) if len(closes) >= 20 else [None] * len(closes)
    )
    rsi_series = (
        _rsi_wilder(closes, 14) if len(closes) > 14 else [None] * len(closes)
    )
    if len(closes) >= 26:
        macd_line, macd_signal, macd_hist = _macd(closes)
    else:
        empty = [None] * len(closes)
        macd_line, macd_signal, macd_hist = empty, empty, empty
    atr_series = (
        _atr_wilder(bars, 14) if len(bars) >= 14 else [None] * len(bars)
    )
    volume_ma20 = (
        _rolling_mean(volumes, 20) if len(volumes) >= 20 else [None] * len(volumes)
    )

    ma5 = ma5_series[last]
    ma20 = ma20_series[last]
    price = closes[last]
    ma_spread_pct = None
    if ma5 is not None and ma20 is not None and ma20 != ZERO:
        ma_spread_pct = ((ma5 - ma20) / ma20) * Decimal("100")

    return_1m = None
    if last >= 1 and closes[last - 1] != ZERO:
        return_1m = ((price - closes[last - 1]) / closes[last - 1]) * Decimal(
            "100"
        )
    return_5m = None
    if last >= 5 and closes[last - 5] != ZERO:
        return_5m = ((price - closes[last - 5]) / closes[last - 5]) * Decimal(
            "100"
        )

    volatility_20m = None
    if len(closes) >= 20:
        window = closes[-20:]
        # 단순 수익률 표준편차 (분봉 %)
        rets: list[Decimal] = []
        for i in range(1, len(window)):
            if window[i - 1] != ZERO:
                rets.append(
                    ((window[i] - window[i - 1]) / window[i - 1])
                    * Decimal("100")
                )
        if len(rets) >= 2:
            volatility_20m = _stddev_population(rets)

    # momentum 수치: 최근 5봉 수익률 (라벨 아님)
    momentum_5m_pct = return_5m

    out: dict[str, Any] = {
        "status": "READY" if ma5 is not None else "PARTIAL",
        "version": "minute_indicator_v1",
        "price": decimal_str(price),
        "ma5": decimal_str(ma5),
        "ma20": decimal_str(ma20),
        "ma_spread_pct": decimal_str(ma_spread_pct),
        "return_1m_pct": decimal_str(return_1m),
        "return_5m_pct": decimal_str(return_5m),
        "momentum_5m_pct": decimal_str(momentum_5m_pct),
        "volatility_20m_pct": decimal_str(volatility_20m),
        "rsi14": decimal_str(rsi_series[last] if rsi_series else None),
        "macd": decimal_str(macd_line[last] if macd_line else None),
        "macd_signal": decimal_str(
            macd_signal[last] if macd_signal else None
        ),
        "macd_histogram": decimal_str(
            macd_hist[last] if macd_hist else None
        ),
        "atr14": decimal_str(atr_series[last] if atr_series else None),
        "volume": decimal_str(volumes[last]),
        "volume_ma20": decimal_str(
            volume_ma20[last] if volume_ma20 else None
        ),
        "ema12": decimal_str(
            (_ema(closes, 12)[last] if len(closes) >= 12 else None)
        ),
        "candle_count_used": len(closes),
    }
    return out
