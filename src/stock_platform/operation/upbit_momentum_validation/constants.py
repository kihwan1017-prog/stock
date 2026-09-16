"""WRK-017 Momentum 60/90d validation — RESEARCH ONLY.

Frozen WRK-016 MOMENTUM rule. Production market.candle_minute 미기록.
"""

from __future__ import annotations

# Frozen thresholds — WRK-016 evaluate_families MOMENTUM (do not retune)
FROZEN_MOMENTUM = {
    "source": "WRK-016 families.evaluate_families MOMENTUM",
    "ret15_min_pct": 0.25,
    "ret60_min_pct": 0.40,
    "ma5_slope_min_pct": 0.0,
    "volume_surge_min": 1.0,
    "ret15_max_pct": 3.0,
    "require_ma5_gt_ma20": True,
    "score": "ret60 + ret15*0.5 + surge*0.2",
}

HORIZONS_MIN = (30, 60, 90, 120, 180)
PRIMARY_CANDIDATES = (60, 120)  # OOS 안정성 비교
