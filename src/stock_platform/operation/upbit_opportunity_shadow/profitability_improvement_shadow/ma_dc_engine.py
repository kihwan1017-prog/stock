# -*- coding: utf-8 -*-
"""MA_DEAD_CROSS_OPTIMIZATION_SHADOW_LAB_V1 — pure decision helpers (SHADOW only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MaDcSnapshot:
    """Baseline MA dead-cross 시점 + forward path 관측."""

    entry_price: float
    baseline_exit_price: float
    current_price: float
    short_ma: float | None
    long_ma: float | None
    short_ma_prev: float | None = None
    long_ma_prev: float | None = None
    short_ma_slope: float | None = None
    long_ma_slope: float | None = None
    mfe_pct: float = 0.0
    unrealized_pnl_pct: float = 0.0
    minutes_since_baseline: float = 0.0
    stop_loss_hit: bool = False
    max_hold_hit: bool = False
    confirmed_dead_cross: bool = False  # short<long for >=2 consecutive observations
    momentum_deteriorating: bool = False
    price_below_long_ma: bool = False


def decide_d0_baseline(snap: MaDcSnapshot) -> dict[str, Any]:
    """D0 = CURRENT_REAL_MA_DEAD_CROSS — baseline 즉시 청산과 동일."""

    return {
        "WOULD_EXIT": True,
        "REASON": "BASELINE_MA_DEAD_CROSS",
        "EXIT_PRICE": snap.baseline_exit_price,
        "DELAY_MINUTES": 0.0,
    }


def decide_d1_confirmed(snap: MaDcSnapshot) -> dict[str, Any]:
    """D1 = CONFIRMED_DEAD_CROSS — 즉시 cross가 아니라 confirmation 후."""

    if snap.stop_loss_hit:
        return {
            "WOULD_EXIT": True,
            "REASON": "STOP_LOSS_PRECEDENCE",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
            "SAFETY_INTERFERENCE": False,
        }
    if snap.max_hold_hit:
        return {
            "WOULD_EXIT": True,
            "REASON": "MAX_HOLD_PRECEDENCE",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
            "SAFETY_INTERFERENCE": False,
        }
    if snap.confirmed_dead_cross:
        return {
            "WOULD_EXIT": True,
            "REASON": "CONFIRMED_DEAD_CROSS",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
        }
    return {"WOULD_EXIT": False, "REASON": "AWAITING_CONFIRMATION"}


def decide_d2_slope_separation(snap: MaDcSnapshot) -> dict[str, Any]:
    """D2 = short/long slope + separation deterioration."""

    if snap.stop_loss_hit:
        return {
            "WOULD_EXIT": True,
            "REASON": "STOP_LOSS_PRECEDENCE",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
        }
    if snap.max_hold_hit:
        return {
            "WOULD_EXIT": True,
            "REASON": "MAX_HOLD_PRECEDENCE",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
        }
    short_s = snap.short_ma_slope
    long_s = snap.long_ma_slope
    sep_bad = False
    if snap.short_ma is not None and snap.long_ma is not None and snap.long_ma > 0:
        sep = (snap.short_ma - snap.long_ma) / snap.long_ma * 100.0
        sep_bad = sep < -0.15
    slope_bad = (
        short_s is not None
        and long_s is not None
        and short_s < 0
        and short_s < long_s
    )
    if sep_bad and slope_bad:
        return {
            "WOULD_EXIT": True,
            "REASON": "SLOPE_SEPARATION_DETERIORATION",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
        }
    if snap.confirmed_dead_cross and sep_bad:
        return {
            "WOULD_EXIT": True,
            "REASON": "CONFIRMED_PLUS_SEPARATION",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
        }
    return {"WOULD_EXIT": False, "REASON": "AWAITING_SLOPE_SEPARATION"}


def decide_d3_mfe_aware(snap: MaDcSnapshot) -> dict[str, Any]:
    """D3 = positive MFE 후 profit erosion 고려. STOP/MAX_HOLD 절대 침범 금지."""

    if snap.stop_loss_hit:
        return {
            "WOULD_EXIT": True,
            "REASON": "STOP_LOSS_PRECEDENCE",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
            "STOP_LOSS_SAFETY_INTERFERENCE": False,
        }
    if snap.max_hold_hit:
        return {
            "WOULD_EXIT": True,
            "REASON": "MAX_HOLD_PRECEDENCE",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
            "MAX_HOLD_SAFETY_INTERFERENCE": False,
        }
    # MFE>=0.5 후 giveback >= 60% of MFE → exit; else wait confirmation
    if snap.mfe_pct >= 0.5:
        giveback = snap.mfe_pct - snap.unrealized_pnl_pct
        if giveback >= snap.mfe_pct * 0.6 and snap.confirmed_dead_cross:
            return {
                "WOULD_EXIT": True,
                "REASON": "MFE_GIVEBACK_WITH_DEAD_CROSS",
                "EXIT_PRICE": snap.current_price,
                "DELAY_MINUTES": snap.minutes_since_baseline,
            }
        if giveback < snap.mfe_pct * 0.35:
            return {"WOULD_EXIT": False, "REASON": "MFE_STILL_INTACT"}
    if snap.confirmed_dead_cross:
        return {
            "WOULD_EXIT": True,
            "REASON": "CONFIRMED_DEAD_CROSS_LOW_MFE",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
        }
    return {"WOULD_EXIT": False, "REASON": "AWAITING_MFE_OR_CONFIRM"}


def decide_d4_contextual(snap: MaDcSnapshot) -> dict[str, Any]:
    """D4 = MA + momentum + price-to-MA. feature 없으면 fail-open to baseline shadow."""

    if snap.stop_loss_hit:
        return {
            "WOULD_EXIT": True,
            "REASON": "STOP_LOSS_PRECEDENCE",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
        }
    if snap.max_hold_hit:
        return {
            "WOULD_EXIT": True,
            "REASON": "MAX_HOLD_PRECEDENCE",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
        }
    features_ok = snap.short_ma is not None and snap.long_ma is not None
    if not features_ok:
        # fail-open to baseline equality evaluation
        return {
            "WOULD_EXIT": True,
            "REASON": "FAIL_OPEN_BASELINE",
            "EXIT_PRICE": snap.baseline_exit_price,
            "DELAY_MINUTES": 0.0,
        }
    score = 0
    if snap.confirmed_dead_cross:
        score += 2
    if snap.momentum_deteriorating:
        score += 1
    if snap.price_below_long_ma:
        score += 1
    if score >= 3:
        return {
            "WOULD_EXIT": True,
            "REASON": "CONTEXTUAL_DEAD_CROSS",
            "EXIT_PRICE": snap.current_price,
            "DELAY_MINUTES": snap.minutes_since_baseline,
        }
    return {"WOULD_EXIT": False, "REASON": "CONTEXT_INSUFFICIENT"}


DECISION_FNS = {
    "D0": decide_d0_baseline,
    "D1": decide_d1_confirmed,
    "D2": decide_d2_slope_separation,
    "D3": decide_d3_mfe_aware,
    "D4": decide_d4_contextual,
}
