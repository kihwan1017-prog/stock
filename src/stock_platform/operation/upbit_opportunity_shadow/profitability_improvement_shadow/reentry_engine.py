"""Lab C — Reentry Anti-Churn pure decisions (shadow only)."""

from __future__ import annotations

from typing import Any

from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.constants import (
    VARIANT_C0,
    VARIANT_C1,
    VARIANT_C2,
    VARIANT_C3,
)


def decide_reentry_block(
    *,
    variant_id: str,
    delay_seconds: float,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """REAL entry를 막지 않음 — shadow WOULD_BLOCK만 반환."""

    ctx = dict(context or {})
    if variant_id == VARIANT_C0:
        return {"WOULD_BLOCK": False, "REASON": "BASELINE_ALLOW"}
    if variant_id == VARIANT_C1:
        block = delay_seconds < 60.0
        return {
            "WOULD_BLOCK": block,
            "REASON": "COOLDOWN_60S" if block else "COOLDOWN_ELAPSED",
        }
    if variant_id == VARIANT_C2:
        block = delay_seconds < 180.0
        return {
            "WOULD_BLOCK": block,
            "REASON": "COOLDOWN_180S" if block else "COOLDOWN_ELAPSED",
        }
    if variant_id == VARIANT_C3:
        if delay_seconds < 180.0:
            return {"WOULD_BLOCK": True, "REASON": "CONTEXTUAL_COOLDOWN_180S"}
        # 독립 confirmation 없으면 block (동일 signal 재사용 금지)
        new_signal = bool(ctx.get("new_signal"))
        ma_improved = bool(ctx.get("ma_improved"))
        momentum_reset = bool(ctx.get("momentum_reset"))
        score_improved = bool(ctx.get("score_improved"))
        confirmed = new_signal or ma_improved or momentum_reset or score_improved
        if not confirmed:
            return {"WOULD_BLOCK": True, "REASON": "NO_INDEPENDENT_CONFIRMATION"}
        return {"WOULD_BLOCK": False, "REASON": "CONTEXTUAL_CONFIRMED"}
    return {"WOULD_BLOCK": False, "REASON": "UNKNOWN_VARIANT"}
