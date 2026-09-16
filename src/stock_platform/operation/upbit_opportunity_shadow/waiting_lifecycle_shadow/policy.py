"""Variant policy helpers — research simulation only (REAL WaitingLifecyclePolicy 불변)."""

from __future__ import annotations

from dataclasses import dataclass

from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.constants import (
    R0_CONSECUTIVE_NO_SIGNAL,
    R0_HARD_EXPIRE_SECONDS,
    R0_SOFT_STALE_SECONDS,
    R1_ABSOLUTE_EXPIRY_SECONDS,
    R1_SOFT_STALE_SECONDS,
    R2_ABSOLUTE_EXPIRY_SECONDS,
    R2_SOFT_STALE_SECONDS,
    R3_ABSOLUTE_EXPIRY_SECONDS,
    R3_REPLACEMENT_SCORE_MARGIN,
    R3_SOFT_STALE_SECONDS,
    VARIANT_R0,
    VARIANT_R1,
    VARIANT_R2,
    VARIANT_R3,
)


@dataclass(frozen=True, slots=True)
class ShadowVariantPolicy:
    variant: str
    soft_stale_seconds: float
    absolute_expiry_seconds: float | None
    """None = REAL-style conjunction expiry (R0 only)."""
    consecutive_no_signal_threshold: int | None
    replacement_score_margin: float | None
    absolute_ttl_ignores_decision: bool
    """True → TECHNICAL_PASS/BUY도 absolute TTL 연장/스킵 금지."""


def policy_for(variant: str) -> ShadowVariantPolicy:
    v = str(variant or "").upper()
    if v == VARIANT_R0:
        return ShadowVariantPolicy(
            variant=VARIANT_R0,
            soft_stale_seconds=R0_SOFT_STALE_SECONDS,
            absolute_expiry_seconds=None,
            consecutive_no_signal_threshold=R0_CONSECUTIVE_NO_SIGNAL,
            replacement_score_margin=None,
            absolute_ttl_ignores_decision=False,
        )
    if v == VARIANT_R1:
        return ShadowVariantPolicy(
            variant=VARIANT_R1,
            soft_stale_seconds=R1_SOFT_STALE_SECONDS,
            absolute_expiry_seconds=R1_ABSOLUTE_EXPIRY_SECONDS,
            consecutive_no_signal_threshold=None,
            replacement_score_margin=None,
            absolute_ttl_ignores_decision=True,
        )
    if v == VARIANT_R2:
        return ShadowVariantPolicy(
            variant=VARIANT_R2,
            soft_stale_seconds=R2_SOFT_STALE_SECONDS,
            absolute_expiry_seconds=R2_ABSOLUTE_EXPIRY_SECONDS,
            consecutive_no_signal_threshold=None,
            replacement_score_margin=None,
            absolute_ttl_ignores_decision=True,
        )
    if v == VARIANT_R3:
        return ShadowVariantPolicy(
            variant=VARIANT_R3,
            soft_stale_seconds=R3_SOFT_STALE_SECONDS,
            absolute_expiry_seconds=R3_ABSOLUTE_EXPIRY_SECONDS,
            consecutive_no_signal_threshold=None,
            replacement_score_margin=R3_REPLACEMENT_SCORE_MARGIN,
            absolute_ttl_ignores_decision=True,
        )
    raise ValueError(f"unknown_waiting_shadow_variant:{variant}")
