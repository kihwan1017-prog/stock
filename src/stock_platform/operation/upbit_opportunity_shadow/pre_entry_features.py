"""진입 직전 path feature — Shadow evaluator에서 stamp (REAL 무관).

batch 분봉 lookback만 사용 — per-symbol fan-out 금지.
실패 시 NOT_AVAILABLE — research fail-open.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence

from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    MinuteBar,
    as_utc,
    return_pct,
)


def _bars_before(
    bars: Sequence[MinuteBar], *, entry_at: datetime, minutes: int
) -> list[MinuteBar]:
    t0 = as_utc(entry_at)
    start = t0 - timedelta(minutes=minutes)
    return [b for b in bars if start <= as_utc(b.candle_at) < t0]


def compute_pre_entry_features(
    bars: Sequence[MinuteBar],
    *,
    entry_at: datetime,
    entry_price: Decimal | float,
) -> dict[str, Any]:
    """진입 직전 1/3/5/10m return + local high distance."""

    try:
        entry = Decimal(str(entry_price))
        if entry <= 0:
            return {"ok": False, "reason": "BAD_ENTRY_PRICE"}
        t0 = as_utc(entry_at)
        out: dict[str, Any] = {"ok": True}

        for m in (1, 3, 5, 10, 15):
            window = _bars_before(bars, entry_at=t0, minutes=m)
            if not window:
                out[f"pre_entry_return_{m}m"] = "NOT_AVAILABLE"
            else:
                # m분 전 close 대비 진입가
                px0 = window[0].close
                out[f"pre_entry_return_{m}m"] = round(
                    float(return_pct(px0, entry)), 6
                )

        for m in (5, 15, 30, 60):
            window = _bars_before(bars, entry_at=t0, minutes=m)
            if not window:
                out[f"dist_from_{m}m_high_pct"] = "NOT_AVAILABLE"
                out[f"dist_from_{m}m_low_pct"] = "NOT_AVAILABLE"
            else:
                hi = max(b.high for b in window)
                lo = min(b.low for b in window)
                if hi <= 0:
                    out[f"dist_from_{m}m_high_pct"] = "NOT_AVAILABLE"
                else:
                    # 0 = at high; negative = below high
                    out[f"dist_from_{m}m_high_pct"] = round(
                        float(return_pct(hi, entry)), 6
                    )
                if lo <= 0:
                    out[f"dist_from_{m}m_low_pct"] = "NOT_AVAILABLE"
                else:
                    # 0 = at low; positive = above low
                    out[f"dist_from_{m}m_low_pct"] = round(
                        float(return_pct(lo, entry)), 6
                    )

        # 최근 변동성 proxy: 15m high-low / entry
        w15 = _bars_before(bars, entry_at=t0, minutes=15)
        if len(w15) >= 3:
            hi = max(b.high for b in w15)
            lo = min(b.low for b in w15)
            out["recent_volatility"] = round(float((hi - lo) / entry * 100), 6)
        else:
            out["recent_volatility"] = "NOT_AVAILABLE"

        # MA slope: 마지막 3개 short/long 분봉 close 단순 기울기 (있으면)
        closes = [float(b.close) for b in _bars_before(bars, entry_at=t0, minutes=20)]
        if len(closes) >= 5:
            out["short_ma_slope"] = round(closes[-1] - closes[-5], 6)
            out["long_ma_slope"] = round(closes[-1] - closes[0], 6)
            out["ma_slope"] = out["short_ma_slope"]
        else:
            out["short_ma_slope"] = "NOT_AVAILABLE"
            out["long_ma_slope"] = "NOT_AVAILABLE"
            out["ma_slope"] = "NOT_AVAILABLE"

        out["volume_acceleration"] = "NOT_AVAILABLE"
        # volume 캔들 미보유 — exhaustion은 volume_surge 외부 stamp에 의존
        out["volume_exhaustion"] = "NOT_AVAILABLE"
        return out
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "reason": str(exc)[:160],
            "pre_entry_return_1m": "NOT_AVAILABLE",
            "pre_entry_return_3m": "NOT_AVAILABLE",
            "pre_entry_return_5m": "NOT_AVAILABLE",
            "pre_entry_return_10m": "NOT_AVAILABLE",
            "pre_entry_return_15m": "NOT_AVAILABLE",
            "dist_from_5m_high_pct": "NOT_AVAILABLE",
            "dist_from_15m_high_pct": "NOT_AVAILABLE",
            "dist_from_30m_high_pct": "NOT_AVAILABLE",
            "dist_from_60m_high_pct": "NOT_AVAILABLE",
            "dist_from_5m_low_pct": "NOT_AVAILABLE",
            "dist_from_15m_low_pct": "NOT_AVAILABLE",
        }
