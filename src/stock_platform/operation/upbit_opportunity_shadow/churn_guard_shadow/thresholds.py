"""Churn Guard threshold variants — configuration/versioned (no magic scatter)."""

from __future__ import annotations

from typing import Any

from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.constants import (
    VARIANT_S0,
    VARIANT_S1,
    VARIANT_S2,
    VARIANT_S3,
)

# 각 variant: WOULD_ALERT 조건. S0은 관찰만 (항상 NO_ALERT).
THRESHOLD_CONFIG: dict[str, dict[str, Any]] = {
    VARIANT_S0: {
        "label": "OBSERVE_ONLY",
        "losing_rt_min": None,
        "reentry_seconds_max": None,
        "same_exit_repeat_min": None,
        "net_loss_min_krw": None,
        "require_compound": False,
        "always_no_alert": True,
    },
    VARIANT_S1: {
        "label": "SENSITIVE",
        "losing_rt_min": 2,
        "reentry_seconds_max": 180,
        "same_exit_repeat_min": 2,
        "net_loss_min_krw": None,
        # OR of short reentry / same exit when losing_rt met
        "require_compound": False,
        "always_no_alert": False,
    },
    VARIANT_S2: {
        "label": "BALANCED",
        "losing_rt_min": 3,
        "reentry_seconds_max": 300,
        "same_exit_repeat_min": 3,
        "net_loss_min_krw": None,
        "require_compound": False,
        "always_no_alert": False,
    },
    VARIANT_S3: {
        "label": "CONSERVATIVE",
        "losing_rt_min": 4,
        "reentry_seconds_max": 600,
        "same_exit_repeat_min": 3,
        "net_loss_min_krw": 200.0,
        "require_compound": True,
        "always_no_alert": False,
    },
}

# Micro-tick: relative (not fixed 1 KRW)
MICRO_TICK_MAX_ABS_PCT = 0.005  # 0.5%
MICRO_TICK_MAX_NOTIONAL_MOVE_RATIO = 0.008  # gross move / turnover
FEE_DOMINANCE_RATIO = 0.35  # fee / |gross| when gross loss small
SHORT_HOLD_SECONDS = 600
RAPID_REENTRY_SECONDS = 180
