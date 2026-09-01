"""V3 shadow exit evaluation — pure logic (REAL mutation 0)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.constants import (
    VARIANT_E1,
    VARIANT_E2,
    VARIANT_E3,
    VARIANT_E4,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.policy import (
    V3PolicyBundle,
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
  ma_dead_cross: bool = False


@dataclass
class ExitDecision:
  should_exit: bool
  exit_reason: str | None = None
  defer: bool = False
  defer_reason: str | None = None
  trigger_reason: str | None = None
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
    if activation_pct <= 0:
        return True
    return _gain_pct(entry, peak) >= activation_pct


def _trailing_triggered(
    peak: Decimal, price: Decimal, trail_drawdown_pct: float
) -> bool:
    if peak <= ZERO:
        return False
    trigger = peak * (ONE := Decimal("1") - Decimal(str(trail_drawdown_pct)) / HUNDRED)
    return price <= trigger


def _tier_trail_drawdown(peak_gain_pct: float, policy: V3PolicyBundle) -> float:
    for tier in policy.e2_tiers:
        lt = tier.get("peak_lt_pct")
        if lt is not None and peak_gain_pct < float(lt):
            return float(
                tier.get("trail_drawdown_pct", policy.real_trailing_drawdown_pct)
            )
    last = policy.e2_tiers[-1] if policy.e2_tiers else {}
    return float(last.get("trail_drawdown_pct", policy.real_trailing_drawdown_pct))


def evaluate_protective_exits(
    snap: PathSnapshot,
    policy: V3PolicyBundle,
) -> ExitDecision | None:
    """STOP_LOSS / MAX_HOLD — 절대 지연하지 않음."""

    loss = _loss_pct(snap.entry_price, snap.current_price)
    if loss >= policy.real_stop_loss_pct:
        return ExitDecision(
            should_exit=True,
            exit_reason="STOP_LOSS",
            trigger_reason="STOP_LOSS",
        )
    if snap.hold_seconds >= policy.real_max_hold_seconds:
        return ExitDecision(
            should_exit=True,
            exit_reason="MAX_HOLD_TIME",
            trigger_reason="MAX_HOLD",
        )
    return None


def evaluate_take_profit(snap: PathSnapshot, policy: V3PolicyBundle) -> ExitDecision | None:
    gain = _gain_pct(snap.entry_price, snap.current_price)
    if gain >= policy.real_take_profit_pct:
        return ExitDecision(
            should_exit=True,
            exit_reason="TAKE_PROFIT",
            trigger_reason="TAKE_PROFIT",
        )
    return None


def evaluate_ma_dead_cross(snap: PathSnapshot) -> ExitDecision | None:
    if snap.ma_dead_cross:
        return ExitDecision(
            should_exit=True,
            exit_reason="MA_DEAD_CROSS",
            trigger_reason="MA_DEAD_CROSS",
        )
    return None


def evaluate_trailing_base(
    snap: PathSnapshot,
    policy: V3PolicyBundle,
    *,
    trail_drawdown_pct: float | None = None,
) -> ExitDecision | None:
    dd = trail_drawdown_pct if trail_drawdown_pct is not None else policy.real_trailing_drawdown_pct
    if not _trailing_armed(
        snap.entry_price, snap.peak_price, policy.real_trailing_activation_pct
    ):
        return None
    if not _trailing_triggered(snap.peak_price, snap.current_price, dd):
        return None
    return ExitDecision(
        should_exit=True,
        exit_reason="TRAILING_STOP",
        trigger_reason="TRAILING_STOP",
        trail_drawdown_pct=dd,
    )


def apply_variant_trailing_defer(
    snap: PathSnapshot,
    policy: V3PolicyBundle,
    variant_id: str,
    base: ExitDecision,
) -> ExitDecision:
    """E1–E4 trailing defer logic — STOP/MAX_HOLD는 호출 전에 처리됨."""

    if not base.should_exit or base.exit_reason != "TRAILING_STOP":
        return base

    gain = _gain_pct(snap.entry_price, snap.current_price)
    fee_adj = gain - policy.round_trip_fee_pct

    if variant_id == VARIANT_E1:
        min_edge = policy.round_trip_fee_pct + policy.e1_min_profit_buffer_pct
        if fee_adj < min_edge:
            return ExitDecision(
                should_exit=False,
                defer=True,
                defer_reason="FEE_AWARE_BELOW_BUFFER",
                trigger_reason=base.trigger_reason,
            )

    elif variant_id == VARIANT_E2:
        pass  # tier trail은 evaluate_variant_exit에서 이미 적용

    elif variant_id == VARIANT_E3:
        if policy.e3_require_short_above_long and snap.short_ma and snap.long_ma:
            if snap.short_ma > snap.long_ma and not snap.ma_dead_cross:
                return ExitDecision(
                    should_exit=False,
                    defer=True,
                    defer_reason="MA_TREND_INTACT",
                    trigger_reason=base.trigger_reason,
                )

    elif variant_id == VARIANT_E4:
        economic_edge = gain - policy.round_trip_fee_pct
        if snap.hold_seconds < 30:
            if snap.mfe_pct < policy.e4_churn_mfe_floor_pct:
                if economic_edge < policy.e4_min_economic_edge_pct:
                    return ExitDecision(
                        should_exit=False,
                        defer=True,
                        defer_reason="ANTI_CHURN_NO_ECONOMIC_EDGE",
                        trigger_reason=base.trigger_reason,
                    )
            elif economic_edge < 0:
                return ExitDecision(
                    should_exit=False,
                    defer=True,
                    defer_reason="ANTI_CHURN_FEE_DOMINATED",
                    trigger_reason=base.trigger_reason,
                )

    return base


def evaluate_variant_exit(
    snap: PathSnapshot,
    policy: V3PolicyBundle,
    variant_id: str,
) -> ExitDecision:
    """우선순위: SL > MAX_HOLD > TRAILING* > TP > MA_DEAD_CROSS."""

    prot = evaluate_protective_exits(snap, policy)
    if prot is not None:
        return prot

    peak_gain = _gain_pct(snap.entry_price, snap.peak_price)
    dd = policy.real_trailing_drawdown_pct
    if variant_id == VARIANT_E2:
        dd = _tier_trail_drawdown(peak_gain, policy)

    trail = evaluate_trailing_base(snap, policy, trail_drawdown_pct=dd)
    if trail is not None:
        return apply_variant_trailing_defer(snap, policy, variant_id, trail)

    tp = evaluate_take_profit(snap, policy)
    if tp is not None:
        return tp

    ma = evaluate_ma_dead_cross(snap)
    if ma is not None:
        return ma

    return ExitDecision(should_exit=False)


def ma_relation_label(
    short_ma: Decimal | None, long_ma: Decimal | None
) -> str | None:
    if short_ma is None or long_ma is None:
        return None
    if short_ma > long_ma:
        return "SHORT_ABOVE_LONG"
    if short_ma < long_ma:
        return "SHORT_BELOW_LONG"
    return "EQUAL"
