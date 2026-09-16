"""Entry Signal Shadow variants E0–E4 — single-gate mild relaxations.

REAL PORTFOLIO_BULLISH thresholds are never mutated.
E0 == CURRENT_REAL. E1–E3 each change one gate only.
E4 ignores SIGNAL_EMIT_SUPPRESSED after technical PASS.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from stock_platform.operation.upbit_full_market.constants import (
    ALLOW_RECOMMENDATIONS,
)
from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
    PortfolioEntryThresholds,
    SymbolEntrySnapshot,
    evaluate_bullish_state_entry,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.constants import (
    VARIANT_E0,
    VARIANT_E1,
    VARIANT_E2,
    VARIANT_E3,
    VARIANT_E4,
)

# REAL baseline SoT (settings defaults)
REAL_RSI_MAX = 70.0
REAL_MIN_MA_SEP_PCT = 0.05
REAL_MIN_VOLUME_SURGE = 0.8

# Mild research grid — small deltas only (no RSI 70→90)
E1_SHORT_MA_TOLERANCE_PCT = -0.02  # allow short slightly below long
E2_MIN_MA_SEP_PCT = 0.03  # match exit sep SoT (milder than 0.05)
E3_RSI_MAX = 75.0  # +5 only


@dataclass(frozen=True, slots=True)
class EntryShadowVariantSpec:
    """Shadow-only entry variant. Exit always REAL baseline."""

    code: str
    description: str
    # None = use REAL evaluate_bullish_state_entry as-is
    short_ma_tolerance_pct: float | None = None
    min_ma_separation_pct: float | None = None
    rsi_max: float | None = None
    # E4: treat technical PASS as entry even if emit suppressed
    ignore_emit_suppression: bool = False


VARIANT_SPECS: dict[str, EntryShadowVariantSpec] = {
    VARIANT_E0: EntryShadowVariantSpec(
        code=VARIANT_E0,
        description="CURRENT_REAL PORTFOLIO_BULLISH (identical)",
    ),
    VARIANT_E1: EntryShadowVariantSpec(
        code=VARIANT_E1,
        description=(
            f"SHORT_MA mild: allow gap_pct>={E1_SHORT_MA_TOLERANCE_PCT}% "
            "(REAL requires short>long)"
        ),
        short_ma_tolerance_pct=E1_SHORT_MA_TOLERANCE_PCT,
    ),
    VARIANT_E2: EntryShadowVariantSpec(
        code=VARIANT_E2,
        description=(
            f"MA_SEPARATION mild: min_sep={E2_MIN_MA_SEP_PCT}% "
            f"(REAL={REAL_MIN_MA_SEP_PCT}%)"
        ),
        min_ma_separation_pct=E2_MIN_MA_SEP_PCT,
    ),
    VARIANT_E3: EntryShadowVariantSpec(
        code=VARIANT_E3,
        description=f"RSI mild: rsi_max={E3_RSI_MAX} (REAL={REAL_RSI_MAX})",
        rsi_max=E3_RSI_MAX,
    ),
    VARIANT_E4: EntryShadowVariantSpec(
        code=VARIANT_E4,
        description=(
            "TECHNICAL_PASS as virtual signal "
            "(ignore SIGNAL_EMIT_SUPPRESSED)"
        ),
        ignore_emit_suppression=True,
    ),
}


def thresholds_for_variant(code: str) -> PortfolioEntryThresholds:
    """Build thresholds for variant — only one gate differs from REAL."""

    spec = VARIANT_SPECS[code]
    return PortfolioEntryThresholds(
        rsi_max=float(spec.rsi_max if spec.rsi_max is not None else REAL_RSI_MAX),
        min_volume_surge=REAL_MIN_VOLUME_SURGE,
        min_ma_separation_pct=float(
            spec.min_ma_separation_pct
            if spec.min_ma_separation_pct is not None
            else REAL_MIN_MA_SEP_PCT
        ),
        max_feed_age_seconds=30.0,
        max_candidate_age_seconds=1800.0,
        require_ai_allow=True,
    )


def evaluate_variant_entry(
    *,
    variant: str,
    short_ma: Decimal,
    long_ma: Decimal,
    snap: SymbolEntrySnapshot | None,
    emit_suppressed: bool = False,
    event_time: Any = None,
    now: Any = None,
) -> dict[str, Any]:
    """Evaluate one variant. Never creates REAL orders."""

    spec = VARIANT_SPECS[variant]
    thresholds = thresholds_for_variant(variant)

    # E1: pre-adjust short_ma gate via tolerance on gap
    if spec.short_ma_tolerance_pct is not None and long_ma != 0:
        gap_pct = float(((short_ma - long_ma) / long_ma) * Decimal("100"))
        if gap_pct < float(spec.short_ma_tolerance_pct):
            return {
                "variant": variant,
                "pass": False,
                "block_reason": "SHORT_MA_NOT_ABOVE_LONG_MA",
                "detail": {
                    "ma_gap_pct": gap_pct,
                    "tolerance_pct": spec.short_ma_tolerance_pct,
                },
            }
        # Force short>long for remaining gates by using adjusted short
        # when within tolerance but short<=long
        if short_ma <= long_ma:
            # synthetic pass of short_ma gate only — bump to epsilon above long
            short_ma = long_ma + Decimal("0.00000001")

    ok, block, detail = evaluate_bullish_state_entry(
        short_ma=short_ma,
        long_ma=long_ma,
        event_time=event_time,
        now=now if now is not None else event_time,
        snap=snap,
        thresholds=thresholds,
    )

    if not ok:
        return {
            "variant": variant,
            "pass": False,
            "block_reason": block,
            "detail": detail,
        }

    # technical PASS
    if emit_suppressed and not spec.ignore_emit_suppression:
        return {
            "variant": variant,
            "pass": False,
            "block_reason": "SIGNAL_EMIT_SUPPRESSED",
            "detail": {**detail, "technical_pass": True},
        }

    return {
        "variant": variant,
        "pass": True,
        "block_reason": None,
        "detail": {
            **detail,
            "technical_pass": True,
            "emit_suppressed_ignored": bool(
                emit_suppressed and spec.ignore_emit_suppression
            ),
        },
    }


def evaluate_all_variants(
    *,
    short_ma: Decimal,
    long_ma: Decimal,
    snap: SymbolEntrySnapshot | None,
    emit_suppressed: bool = False,
    event_time: Any = None,
    now: Any = None,
) -> dict[str, dict[str, Any]]:
    return {
        code: evaluate_variant_entry(
            variant=code,
            short_ma=short_ma,
            long_ma=long_ma,
            snap=snap,
            emit_suppressed=emit_suppressed,
            event_time=event_time,
            now=now,
        )
        for code in VARIANT_SPECS
    }


def attribution_from_e0_block(block_reason: str | None) -> str:
    """Map E0 block to attribution bucket."""

    if block_reason is None:
        return "PASS_E0"
    if block_reason == "SHORT_MA_NOT_ABOVE_LONG_MA":
        return "BLOCKED_BY_SHORT_MA"
    if block_reason == "MA_SEPARATION_TOO_SMALL":
        return "BLOCKED_BY_MA_SEPARATION"
    if block_reason == "RSI_TOO_HIGH":
        return "BLOCKED_BY_RSI"
    if block_reason == "SIGNAL_EMIT_SUPPRESSED":
        return "BLOCKED_BY_SIGNAL_SUPPRESSION"
    return f"BLOCKED_BY_{block_reason}"
