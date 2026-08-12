"""분봉 → 지표 변환 및 급등락 필터."""

from __future__ import annotations

from typing import Any

from stock_platform.ai.market_analysis.minute_indicators import (
    compute_minute_chart_indicators,
)


def upbit_minute_rows_to_candles(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Upbit minute candle JSON → indicator helper 입력 (시간 오름차순)."""

    candles: list[dict[str, Any]] = []
    for row in reversed(rows):  # API는 최신 먼저
        if not isinstance(row, dict):
            continue
        try:
            candles.append(
                {
                    "open": row.get("opening_price"),
                    "high": row.get("high_price"),
                    "low": row.get("low_price"),
                    "close": row.get("trade_price"),
                    "volume": row.get("candle_acc_trade_volume"),
                }
            )
        except Exception:  # noqa: BLE001
            continue
    return candles


def build_indicator_snapshot(
    candle_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    candles = upbit_minute_rows_to_candles(candle_rows)
    return compute_minute_chart_indicators(candles)


def is_abnormal_spike(
    *,
    max_spike_pct: float,
    return_5m_pct: float | None,
    return_1m_pct: float | None = None,
    volatility_20m_pct: float | None = None,
) -> bool:
    """펌핑성 급등/비정상 변동성 — candidate 제외."""

    r5 = abs(float(return_5m_pct or 0.0))
    r1 = abs(float(return_1m_pct or 0.0))
    if r5 >= float(max_spike_pct) or r1 >= float(max_spike_pct):
        return True
    vol = float(volatility_20m_pct or 0.0)
    # 분봉 변동성 %가 과도하면 제외 (보수)
    if vol >= max(float(max_spike_pct) * 0.15, 0.5):
        return True
    return False


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
