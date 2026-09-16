"""Versioned V3 shadow policy — DB override + defaults."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.constants import (
    POLICY_ANTI_CHURN_TRAILING_V1,
    POLICY_FEE_AWARE_TRAILING_V1,
    POLICY_MA_CONFIRM_TRAILING_V1,
    POLICY_PEAK_TIERED_TRAILING_V1,
    REAL_MAX_HOLD_SECONDS,
    REAL_STOP_LOSS_PCT,
    REAL_TAKE_PROFIT_PCT,
    REAL_TRAILING_ACTIVATION_PCT,
    REAL_TRAILING_DRAWDOWN_PCT,
    VARIANT_E1,
    VARIANT_E2,
    VARIANT_E3,
    VARIANT_E4,
)

# Upbit round-trip taker fee ≈ 0.05% × 2
DEFAULT_ROUND_TRIP_FEE_PCT = 0.10


@dataclass(frozen=True)
class V3PolicyBundle:
    policy_version: str
    real_stop_loss_pct: float
    real_take_profit_pct: float
    real_trailing_activation_pct: float
    real_trailing_drawdown_pct: float
    real_max_hold_seconds: int
    round_trip_fee_pct: float
    e1_min_profit_buffer_pct: float
    e2_tiers: tuple[dict[str, float], ...]
    e3_require_short_above_long: bool
    e4_min_economic_edge_pct: float
    e4_churn_mfe_floor_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "real_stop_loss_pct": self.real_stop_loss_pct,
            "real_take_profit_pct": self.real_take_profit_pct,
            "real_trailing_activation_pct": self.real_trailing_activation_pct,
            "real_trailing_drawdown_pct": self.real_trailing_drawdown_pct,
            "real_max_hold_seconds": self.real_max_hold_seconds,
            "round_trip_fee_pct": self.round_trip_fee_pct,
            "e1_min_profit_buffer_pct": self.e1_min_profit_buffer_pct,
            "e2_tiers": list(self.e2_tiers),
            "e3_require_short_above_long": self.e3_require_short_above_long,
            "e4_min_economic_edge_pct": self.e4_min_economic_edge_pct,
            "e4_churn_mfe_floor_pct": self.e4_churn_mfe_floor_pct,
        }


DEFAULT_POLICY = V3PolicyBundle(
    policy_version="exit_opt_shadow_v3_default_20260902",
    real_stop_loss_pct=REAL_STOP_LOSS_PCT,
    real_take_profit_pct=REAL_TAKE_PROFIT_PCT,
    real_trailing_activation_pct=REAL_TRAILING_ACTIVATION_PCT,
    real_trailing_drawdown_pct=REAL_TRAILING_DRAWDOWN_PCT,
    real_max_hold_seconds=REAL_MAX_HOLD_SECONDS,
    round_trip_fee_pct=DEFAULT_ROUND_TRIP_FEE_PCT,
    e1_min_profit_buffer_pct=0.15,
    e2_tiers=(
        {"peak_lt_pct": 1.5, "trail_drawdown_pct": 0.8},
        {"peak_lt_pct": 2.5, "trail_drawdown_pct": 1.0},
        {"peak_lt_pct": None, "trail_drawdown_pct": 1.2},
    ),
    e3_require_short_above_long=True,
    e4_min_economic_edge_pct=0.12,
    e4_churn_mfe_floor_pct=0.25,
)


def variant_policy_id(variant_id: str) -> str:
    return {
        VARIANT_E1: POLICY_FEE_AWARE_TRAILING_V1,
        VARIANT_E2: POLICY_PEAK_TIERED_TRAILING_V1,
        VARIANT_E3: POLICY_MA_CONFIRM_TRAILING_V1,
        VARIANT_E4: POLICY_ANTI_CHURN_TRAILING_V1,
    }.get(variant_id, "CURRENT_REAL")


def load_policy_bundle(
    session: Session | None = None,
    *,
    policy_version: str | None = None,
) -> V3PolicyBundle:
    """DB policy row가 있으면 overlay, 없으면 DEFAULT."""

    if session is None:
        return DEFAULT_POLICY
    try:
        from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.entities import (
            UpbitExitOptimizationShadowV3PolicyEntity,
        )

        q = select(UpbitExitOptimizationShadowV3PolicyEntity).where(
            UpbitExitOptimizationShadowV3PolicyEntity.active.is_(True)
        )
        if policy_version:
            q = q.where(
                UpbitExitOptimizationShadowV3PolicyEntity.policy_version
                == policy_version
            )
        row = session.scalar(q.order_by(
            UpbitExitOptimizationShadowV3PolicyEntity.policy_id.desc()
        ))
        if row is None:
            return DEFAULT_POLICY
        blob = dict(row.policy_json or {})
        tiers = blob.get("e2_tiers") or DEFAULT_POLICY.e2_tiers
        return V3PolicyBundle(
            policy_version=str(row.policy_version),
            real_stop_loss_pct=float(
                blob.get("real_stop_loss_pct", DEFAULT_POLICY.real_stop_loss_pct)
            ),
            real_take_profit_pct=float(
                blob.get("real_take_profit_pct", DEFAULT_POLICY.real_take_profit_pct)
            ),
            real_trailing_activation_pct=float(
                blob.get(
                    "real_trailing_activation_pct",
                    DEFAULT_POLICY.real_trailing_activation_pct,
                )
            ),
            real_trailing_drawdown_pct=float(
                blob.get(
                    "real_trailing_drawdown_pct",
                    DEFAULT_POLICY.real_trailing_drawdown_pct,
                )
            ),
            real_max_hold_seconds=int(
                blob.get("real_max_hold_seconds", DEFAULT_POLICY.real_max_hold_seconds)
            ),
            round_trip_fee_pct=float(
                blob.get("round_trip_fee_pct", DEFAULT_POLICY.round_trip_fee_pct)
            ),
            e1_min_profit_buffer_pct=float(
                blob.get(
                    "e1_min_profit_buffer_pct",
                    DEFAULT_POLICY.e1_min_profit_buffer_pct,
                )
            ),
            e2_tiers=tuple(tiers),
            e3_require_short_above_long=bool(
                blob.get(
                    "e3_require_short_above_long",
                    DEFAULT_POLICY.e3_require_short_above_long,
                )
            ),
            e4_min_economic_edge_pct=float(
                blob.get(
                    "e4_min_economic_edge_pct",
                    DEFAULT_POLICY.e4_min_economic_edge_pct,
                )
            ),
            e4_churn_mfe_floor_pct=float(
                blob.get(
                    "e4_churn_mfe_floor_pct",
                    DEFAULT_POLICY.e4_churn_mfe_floor_pct,
                )
            ),
        )
    except Exception:  # noqa: BLE001
        return DEFAULT_POLICY
