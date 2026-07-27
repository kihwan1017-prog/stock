"""STEP 11-7 — Decimal/Candle 정규화 (float·NaN 금지)."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any

from stock_platform.ai.market_analysis.constants import DECIMAL_JSON_PLACES


def to_decimal(value: Any) -> Decimal:
    if value is None:
        raise ValueError("NULL_NUMERIC")
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("NAN_OR_INFINITY")
        value = str(value)
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("INVALID_DECIMAL") from exc
    if not d.is_finite():
        raise ValueError("NAN_OR_INFINITY")
    return d


def decimal_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    q = Decimal("1").scaleb(-DECIMAL_JSON_PLACES)
    return format(value.quantize(q), "f")


def validate_ohlc(
    *,
    open_price: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal,
) -> list[str]:
    flags: list[str] = []
    if volume < 0:
        flags.append("NEGATIVE_VOLUME")
    if high < low:
        flags.append("HIGH_BELOW_LOW")
    if high < open_price or high < close:
        flags.append("HIGH_INCONSISTENT")
    if low > open_price or low > close:
        flags.append("LOW_INCONSISTENT")
    return flags


def normalize_candle_row(row: dict[str, Any]) -> dict[str, Any]:
    o = to_decimal(row["open"])
    h = to_decimal(row["high"])
    l = to_decimal(row["low"])
    c = to_decimal(row["close"])
    v = to_decimal(row.get("volume") or 0)
    flags = validate_ohlc(
        open_price=o, high=h, low=l, close=c, volume=v
    )
    quote_vol = None
    if row.get("quote_volume") is not None:
        quote_vol = decimal_str(to_decimal(row["quote_volume"]))
    return {
        "open_time": row.get("open_time"),
        "close_time": row.get("close_time"),
        "open": decimal_str(o),
        "high": decimal_str(h),
        "low": decimal_str(l),
        "close": decimal_str(c),
        "volume": decimal_str(v),
        "quote_volume": quote_vol,
        "is_complete": bool(row.get("is_complete", True)),
        "source": row.get("source"),
        "adjusted": bool(row.get("adjusted", False)),
        "quality_flags": flags,
    }
