# -*- coding: utf-8 -*-
"""Deterministic market regime labels — OBSERVATION ONLY."""

from __future__ import annotations

from typing import Any

from stock_platform.operation.upbit_strategy_observability.constants import (
    REGIME_BTC_DOWN_PCT,
    REGIME_BTC_UP_PCT,
    SIDEWAYS_MOVE_VS_RANGE,
)


def classify_btc_trend(ret_15m_pct: float | None) -> str:
    if ret_15m_pct is None:
        return "UNKNOWN"
    if ret_15m_pct >= REGIME_BTC_UP_PCT:
        return "UP"
    if ret_15m_pct <= REGIME_BTC_DOWN_PCT:
        return "DOWN"
    return "SIDEWAYS"


def classify_symbol_regime(
    *,
    ret_30m_pct: float | None,
    range_pct_30m: float | None,
    atr_proxy: float | None = None,
) -> str:
    if ret_30m_pct is None or range_pct_30m is None:
        return "UNKNOWN"
    if atr_proxy is not None and atr_proxy >= 1.5 and abs(ret_30m_pct) < 0.4:
        return "HIGH_VOLATILITY"
    if range_pct_30m > 0 and abs(ret_30m_pct) < SIDEWAYS_MOVE_VS_RANGE * range_pct_30m:
        return "SIDEWAYS"
    if ret_30m_pct >= 0.4:
        return "TREND_UP"
    if ret_30m_pct <= -0.4:
        return "TREND_DOWN"
    return "SIDEWAYS"


def regime_formula_doc() -> dict[str, Any]:
    return {
        "observation_only": True,
        "used_in_trading_decision": False,
        "btc_up_pct_ge": REGIME_BTC_UP_PCT,
        "btc_down_pct_le": REGIME_BTC_DOWN_PCT,
        "sideways_if_abs_ret_lt": f"{SIDEWAYS_MOVE_VS_RANGE} * range_pct_30m",
    }
