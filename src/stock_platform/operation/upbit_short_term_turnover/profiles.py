"""Research profile definitions — shadow only."""

from __future__ import annotations

from dataclasses import dataclass

from stock_platform.operation.upbit_opportunity_shadow.exit_policy_ab import (
    ExitPolicySpec,
)
from stock_platform.realtime.ma_exit_policy import (
    DEFAULT_EXIT_MIN_MA_SEPARATION_PCT,
    DEFAULT_MA_EXIT_MIN_HOLDING_SECONDS,
)


@dataclass(frozen=True, slots=True)
class ResearchProfile:
    """단기 회전 연구 프로필."""

    key: str
    slot_policy: str  # BROKER_ALL | AUTO_ONLY_SHADOW
    exit_spec: ExitPolicySpec
    horizon_minutes: int
    reentry_cooldown_seconds: int | None = None


def _spec(
    label: str,
    *,
    tp: float,
    sl: float,
    trail: float,
    act: float | None,
) -> ExitPolicySpec:
    return ExitPolicySpec(
        label=label,
        tp_pct=tp,
        sl_pct=sl,
        trail_distance_pct=trail,
        trail_activation_pct=act,
        ma_exit_enabled=True,
        exit_min_ma_separation_pct=DEFAULT_EXIT_MIN_MA_SEPARATION_PCT,
        ma_exit_min_holding_seconds=DEFAULT_MA_EXIT_MIN_HOLDING_SECONDS,
    )


PROFILE_SPECS: dict[str, ResearchProfile] = {
    "BASELINE": ResearchProfile(
        key="BASELINE",
        slot_policy="BROKER_ALL",
        exit_spec=_spec(
            "BASELINE", tp=10.0, sl=5.0, trail=3.0, act=None
        ),
        horizon_minutes=1440,
        reentry_cooldown_seconds=300,
    ),
    "CONSERVATIVE_TURNOVER": ResearchProfile(
        key="CONSERVATIVE_TURNOVER",
        slot_policy="AUTO_ONLY_SHADOW",
        exit_spec=_spec(
            "CONSERVATIVE_TURNOVER",
            tp=1.5,
            sl=1.0,
            trail=0.8,
            act=0.6,
        ),
        horizon_minutes=240,
        reentry_cooldown_seconds=900,
    ),
    "BALANCED_TURNOVER": ResearchProfile(
        key="BALANCED_TURNOVER",
        slot_policy="AUTO_ONLY_SHADOW",
        exit_spec=_spec(
            "BALANCED_TURNOVER",
            tp=1.2,
            sl=0.8,
            trail=0.6,
            act=0.5,
        ),
        horizon_minutes=120,
        reentry_cooldown_seconds=600,
    ),
    "AGGRESSIVE_TURNOVER": ResearchProfile(
        key="AGGRESSIVE_TURNOVER",
        slot_policy="AUTO_ONLY_SHADOW",
        exit_spec=_spec(
            "AGGRESSIVE_TURNOVER",
            tp=0.8,
            sl=0.5,
            trail=0.4,
            act=0.4,
        ),
        horizon_minutes=60,
        reentry_cooldown_seconds=300,
    ),
}
