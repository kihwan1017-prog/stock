"""Lab B — Exit Optimization V4 pure evaluation (no orders)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.constants import (
    B1_MIN_PROFIT_BUFFER_PCT,
    B2_MFE_LOCK_GTE,
    B2_MFE_MICRO_LT,
    B2_TRAIL_LOCK,
    B2_TRAIL_MICRO,
    B2_TRAIL_MID,
    REAL_MAX_HOLD_SECONDS,
    REAL_STOP_LOSS_PCT,
    REAL_TAKE_PROFIT_PCT,
    REAL_TRAILING_ACTIVATION_PCT,
    REAL_TRAILING_DRAWDOWN_PCT,
    ROUND_TRIP_FEE_PCT,
    VARIANT_B0,
    VARIANT_B1,
    VARIANT_B2,
    VARIANT_B3,
)

ZERO = Decimal("0")
HUNDRED = Decimal("100")


@dataclass
class PathSnapshot:
    entry_price: Decimal
    current_price: Decimal
    peak_price: Decimal
    hold_seconds: float
    mfe_pct: float
    mae_pct: float
    short_ma: Decimal | None = None
    long_ma: Decimal | None = None
    macd: float | None = None
    ma_dead_cross: bool = False


@dataclass
class ExitDecision:
    should_exit: bool
    exit_reason: str | None = None
    defer: bool = False
    defer_reason: str | None = None
    trail_drawdown_pct: float | None = None


def _gain_pct(entry: Decimal, price: Decimal) -> float:
    if entry <= ZERO:
        return 0.0
    return float((price - entry) / entry * HUNDRED)


def _loss_pct(entry: Decimal, price: Decimal) -> float:
    return -_gain_pct(entry, price)


def _trailing_armed(entry: Decimal, peak: Decimal, activation_pct: float) -> bool:
    if peak <= entry:
        return False
    return _gain_pct(entry, peak) >= activation_pct


def _trailing_triggered(peak: Decimal, price: Decimal, trail_dd: float) -> bool:
    if peak <= ZERO:
        return False
    trigger = peak * (Decimal("1") - Decimal(str(trail_dd)) / HUNDRED)
    return price <= trigger


def mfe_adaptive_trail_dd(mfe_pct: float) -> float:
    """2026-09-02 분포 기반 deterministic bucket (micro noise vs lock)."""

    if mfe_pct < B2_MFE_MICRO_LT:
        return B2_TRAIL_MICRO
    if mfe_pct >= B2_MFE_LOCK_GTE:
        return B2_TRAIL_LOCK
    return B2_TRAIL_MID


def evaluate_protective(snap: PathSnapshot) -> ExitDecision | None:
    """STOP_LOSS / MAX_HOLD — 절대 지연 금지."""

    if _loss_pct(snap.entry_price, snap.current_price) >= REAL_STOP_LOSS_PCT:
        return ExitDecision(True, "STOP_LOSS")
    if snap.hold_seconds >= REAL_MAX_HOLD_SECONDS:
        return ExitDecision(True, "MAX_HOLD_TIME")
    return None


def evaluate_take_profit(snap: PathSnapshot) -> ExitDecision | None:
    if _gain_pct(snap.entry_price, snap.current_price) >= REAL_TAKE_PROFIT_PCT:
        return ExitDecision(True, "TAKE_PROFIT")
    return None


def evaluate_ma_dead(snap: PathSnapshot) -> ExitDecision | None:
    if snap.ma_dead_cross:
        return ExitDecision(True, "MA_DEAD_CROSS")
    return None


def evaluate_trailing(snap: PathSnapshot, trail_dd: float) -> ExitDecision | None:
    if not _trailing_armed(
        snap.entry_price, snap.peak_price, REAL_TRAILING_ACTIVATION_PCT
    ):
        return None
    if not _trailing_triggered(snap.peak_price, snap.current_price, trail_dd):
        return None
    return ExitDecision(
        True, "TRAILING_STOP", trail_drawdown_pct=trail_dd
    )


def apply_b1_fee_lock(snap: PathSnapshot, base: ExitDecision) -> ExitDecision:
    if not base.should_exit or base.exit_reason != "TRAILING_STOP":
        return base
    gain = _gain_pct(snap.entry_price, snap.current_price)
    min_edge = ROUND_TRIP_FEE_PCT + B1_MIN_PROFIT_BUFFER_PCT
    if gain < min_edge:
        return ExitDecision(
            False,
            defer=True,
            defer_reason="FEE_AWARE_PROFIT_LOCK",
            trail_drawdown_pct=base.trail_drawdown_pct,
        )
    return base


def apply_b3_ma_state(snap: PathSnapshot, base: ExitDecision) -> ExitDecision:
    if not base.should_exit or base.exit_reason != "TRAILING_STOP":
        return base
    strong = False
    if snap.short_ma and snap.long_ma and snap.short_ma > snap.long_ma:
        if snap.current_price >= snap.short_ma and not snap.ma_dead_cross:
            if snap.macd is None or snap.macd >= 0:
                strong = True
    if strong:
        return ExitDecision(
            False,
            defer=True,
            defer_reason="MA_STATE_TREND_INTACT",
            trail_drawdown_pct=base.trail_drawdown_pct,
        )
    return base


def evaluate_variant_exit(snap: PathSnapshot, variant_id: str) -> ExitDecision:
    prot = evaluate_protective(snap)
    if prot:
        return prot
    tp = evaluate_take_profit(snap)
    if tp:
        return tp
    dead = evaluate_ma_dead(snap)
    if dead:
        return dead

    if variant_id == VARIANT_B2:
        trail_dd = mfe_adaptive_trail_dd(snap.mfe_pct)
    else:
        trail_dd = REAL_TRAILING_DRAWDOWN_PCT

    base = evaluate_trailing(snap, trail_dd)
    if base is None:
        return ExitDecision(False)

    if variant_id == VARIANT_B0:
        return base
    if variant_id == VARIANT_B1:
        return apply_b1_fee_lock(snap, base)
    if variant_id == VARIANT_B2:
        return base  # adaptive trail already applied
    if variant_id == VARIANT_B3:
        return apply_b3_ma_state(snap, base)
    return base
