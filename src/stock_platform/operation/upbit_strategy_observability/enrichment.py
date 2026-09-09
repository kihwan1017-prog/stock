# -*- coding: utf-8 -*-
"""Side-channel chasing / regime enrichment from candle DB only.

OBSERVATION ONLY — never imported by trading decision modules for gates.
No broker/API polling.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_strategy_observability.constants import (
    DQ_AVAILABLE,
    DQ_NOT_COLLECTED_RATE_LIMIT_SAFETY,
    DQ_SOURCE_DATA_MISSING,
    ORDERBOOK_POLICY,
)
from stock_platform.operation.upbit_strategy_observability.data_quality import (
    field_status,
    null_with_reason,
)
from stock_platform.operation.upbit_strategy_observability.regime import (
    classify_btc_trend,
    classify_symbol_regime,
    regime_formula_doc,
)

logger = logging.getLogger(__name__)

LOOKAHEAD_ANALYTICS_ONLY = False  # past candles only for chasing
MUST_NOT_DRIVE_TRADING = True
NO_BROKER_API = True


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _load_minute_closes(
    session: Session, *, symbol: str, start: datetime, end: datetime
) -> list[tuple[datetime, float, float, float]]:
    rows = session.execute(
        text(
            """
            SELECT c.candle_at, c.close_price::float8, c.high_price::float8, c.low_price::float8
            FROM market.candle_minute c
            JOIN market.instrument i ON i.instrument_id = c.instrument_id
            WHERE i.exchange_code='UPBIT' AND i.symbol=:sym AND c.timeframe=1
              AND c.candle_at >= :s AND c.candle_at <= :e
            ORDER BY c.candle_at
            """
        ),
        {"sym": symbol.upper(), "s": start, "e": end},
    ).all()
    out: list[tuple[datetime, float, float, float]] = []
    for ca, close, high, low in rows:
        ca = _aware(ca)
        out.append((ca, float(close), float(high), float(low)))
    return out


def _price_at_offset(
    series: list[tuple[datetime, float, float, float]],
    *,
    at: datetime,
    minutes_ago: int,
    tol_sec: int = 90,
) -> float | None:
    target = at - timedelta(minutes=minutes_ago)
    best = None
    best_d = None
    for ca, close, _h, _l in series:
        d = abs((ca - target).total_seconds())
        if d <= tol_sec and (best_d is None or d < best_d):
            best_d = d
            best = close
    return best


def _window_high_low(
    series: list[tuple[datetime, float, float, float]],
    *,
    at: datetime,
    window_m: int,
) -> tuple[float | None, float | None]:
    start = at - timedelta(minutes=window_m)
    highs: list[float] = []
    lows: list[float] = []
    for ca, _c, high, low in series:
        if start <= ca <= at:
            highs.append(high)
            lows.append(low)
    if not highs:
        return None, None
    return max(highs), min(lows)


def estimate_golden_cross_age_seconds(
    series: list[tuple[datetime, float, float, float]],
    *,
    at: datetime,
    short_window: int = 5,
    long_window: int = 20,
) -> dict[str, Any]:
    """Approx golden-cross age from minute closes (observation-only heuristic)."""

    if len(series) < long_window + 2:
        return null_with_reason(
            DQ_SOURCE_DATA_MISSING, "INSUFFICIENT_CANDLES_FOR_MA_CROSS"
        )
    closes = [c for _ca, c, _h, _l in series]

    def sma(end_idx: int, w: int) -> float | None:
        if end_idx + 1 < w:
            return None
        chunk = closes[end_idx + 1 - w : end_idx + 1]
        return sum(chunk) / w

    # series aligned to end ~= at
    last_idx = len(closes) - 1
    age = None
    for i in range(last_idx, long_window, -1):
        s0 = sma(i - 1, short_window)
        l0 = sma(i - 1, long_window)
        s1 = sma(i, short_window)
        l1 = sma(i, long_window)
        if None in (s0, l0, s1, l1):
            continue
        if s0 <= l0 and s1 > l1:
            ca = series[i][0]
            age = int((at - ca).total_seconds())
            break
    if age is None:
        return null_with_reason(DQ_SOURCE_DATA_MISSING, "NO_GOLDEN_CROSS_IN_WINDOW")
    return field_status(value=age, status=DQ_AVAILABLE, reason="CANDLE_MINUTE_SMA")


def build_chasing_metrics(
    session: Session,
    *,
    symbol: str,
    at: datetime,
    price: float | None = None,
) -> dict[str, Any]:
    """Candle-only chasing / late-entry metrics. Never blocks trading."""

    at_u = _aware(at)
    start = at_u - timedelta(minutes=90)
    series = _load_minute_closes(session, symbol=symbol, start=start, end=at_u)
    out: dict[str, Any] = {
        "observation_only": True,
        "used_in_trading_decision": False,
        "broker_api": "NONE",
        "orderbook": ORDERBOOK_POLICY,
    }
    if not series:
        out["data_quality"] = DQ_SOURCE_DATA_MISSING
        for k in (
            "golden_cross_age_seconds",
            "recent_return_1m",
            "recent_return_3m",
            "recent_return_5m",
            "recent_return_10m",
            "recent_return_15m",
            "recent_return_30m",
            "recent_high_5m",
            "recent_high_15m",
            "recent_high_30m",
            "distance_from_high_5m_pct",
            "distance_from_high_15m_pct",
            "distance_from_high_30m_pct",
            "range_position_5m",
            "range_position_15m",
            "range_position_30m",
        ):
            out[k] = null_with_reason(DQ_SOURCE_DATA_MISSING, "NO_CANDLE_ROWS")
        return out

    last_px = price if price and price > 0 else series[-1][1]
    out["data_quality"] = DQ_AVAILABLE
    out["golden_cross_age_seconds"] = estimate_golden_cross_age_seconds(
        series, at=at_u
    )

    for m in (1, 3, 5, 10, 15, 30):
        past = _price_at_offset(series, at=at_u, minutes_ago=m)
        key = f"recent_return_{m}m"
        if past is None or past <= 0:
            out[key] = null_with_reason(
                DQ_SOURCE_DATA_MISSING, f"NO_CLOSE_AT_{m}M"
            )
        else:
            out[key] = field_status(
                value=round((last_px / past - 1.0) * 100.0, 8),
                status=DQ_AVAILABLE,
            )

    for w in (5, 15, 30):
        hi, lo = _window_high_low(series, at=at_u, window_m=w)
        hk = f"recent_high_{w}m"
        dk = f"distance_from_high_{w}m_pct"
        rk = f"range_position_{w}m"
        if hi is None or hi <= 0:
            out[hk] = null_with_reason(DQ_SOURCE_DATA_MISSING, f"NO_HIGH_{w}M")
            out[dk] = null_with_reason(DQ_SOURCE_DATA_MISSING, f"NO_HIGH_{w}M")
            out[rk] = null_with_reason(DQ_SOURCE_DATA_MISSING, f"NO_RANGE_{w}M")
            continue
        out[hk] = field_status(value=hi, status=DQ_AVAILABLE)
        out[dk] = field_status(
            value=round((last_px / hi - 1.0) * 100.0, 8),
            status=DQ_AVAILABLE,
        )
        if lo is None or hi <= lo:
            out[rk] = null_with_reason(DQ_SOURCE_DATA_MISSING, f"FLAT_RANGE_{w}M")
        else:
            out[rk] = field_status(
                value=round((last_px - lo) / (hi - lo), 8),
                status=DQ_AVAILABLE,
            )

    out["orderbook_note"] = null_with_reason(
        DQ_NOT_COLLECTED_RATE_LIMIT_SAFETY, ORDERBOOK_POLICY
    )
    return out


def build_regime_from_candles(
    session: Session, *, at: datetime
) -> dict[str, Any]:
    """BTC/ETH returns from candle DB — observation only, no broker calls."""

    at_u = _aware(at)
    start = at_u - timedelta(hours=2)
    payload: dict[str, Any] = {
        "observation_only": True,
        "used_in_trading_decision": False,
        "broker_api": "NONE",
        "formula": regime_formula_doc(),
    }
    for sym, key in (("KRW-BTC", "btc"), ("KRW-ETH", "eth")):
        series = _load_minute_closes(session, symbol=sym, start=start, end=at_u)
        returns: dict[str, Any] = {}
        if not series:
            for m in (5, 15, 60):
                returns[f"return_{m}m"] = null_with_reason(
                    DQ_SOURCE_DATA_MISSING, f"NO_{sym}_CANDLES"
                )
            payload[key] = returns
            continue
        last = series[-1][1]
        for m in (5, 15, 60):
            past = _price_at_offset(series, at=at_u, minutes_ago=m)
            rk = f"return_{m}m"
            if past is None or past <= 0:
                returns[rk] = null_with_reason(
                    DQ_SOURCE_DATA_MISSING, f"NO_{sym}_CLOSE_{m}M"
                )
            else:
                returns[rk] = field_status(
                    value=round((last / past - 1.0) * 100.0, 8),
                    status=DQ_AVAILABLE,
                )
        payload[key] = returns
        if key == "btc":
            v15 = returns.get("return_15m", {}).get("value")
            payload["btc_trend"] = classify_btc_trend(v15)
    # Symbol regime left to caller when symbol returns known
    payload["symbol_regime_helper"] = "classify_symbol_regime"
    return payload


def classify_symbol_from_chasing(chasing: dict[str, Any]) -> str:
    ret = (chasing.get("recent_return_30m") or {}).get("value")
    hi = (chasing.get("recent_high_30m") or {}).get("value")
    # rough range proxy: use distance if available
    if ret is None:
        return "UNKNOWN"
    range_pct = None
    if hi and chasing.get("recent_return_30m"):
        # approximate range from high-low via range_position if both ends known
        rp = (chasing.get("range_position_30m") or {}).get("value")
        if rp is not None and hi:
            range_pct = abs(float(ret)) / max(rp, 0.05) if rp else abs(float(ret)) * 2
    return classify_symbol_regime(ret_30m_pct=float(ret), range_pct_30m=range_pct or abs(float(ret)) * 3)
