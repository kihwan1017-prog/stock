"""Lab C — Reentry Anti-Churn pure decisions (shadow only)."""

from __future__ import annotations

from typing import Any

from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.constants import (
    VARIANT_C0,
    VARIANT_C1,
    VARIANT_C2,
    VARIANT_C3,
)


def _tri_flag(ctx: dict[str, Any], *keys: str) -> bool | str:
    """True/False/UNKNOWN — bool()로 UNKNOWN을 False로 날조하지 않음."""

    for key in keys:
        if key not in ctx:
            continue
        raw = ctx.get(key)
        if raw is None:
            return "UNKNOWN"
        if isinstance(raw, str) and raw.strip().upper() in {
            "",
            "UNKNOWN",
            "NOT_RECORDED",
        }:
            return "UNKNOWN"
        if isinstance(raw, str) and raw.strip().upper() in {"TRUE", "1", "YES"}:
            return True
        if isinstance(raw, str) and raw.strip().upper() in {"FALSE", "0", "NO"}:
            return False
        if isinstance(raw, bool):
            return raw
        return "UNKNOWN"
    return "UNKNOWN"


def decide_reentry_block(
    *,
    variant_id: str,
    delay_seconds: float,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """REAL entry를 막지 않음 — shadow WOULD_BLOCK + SHADOW_DECISION 반환.

    SHADOW_DECISION ∈ {ALLOW, BLOCK, UNKNOWN} — NULL 금지.
    """

    def _pack(
        *,
        would_block: bool,
        reason: str,
        shadow_decision: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision = str(shadow_decision or "UNKNOWN").upper()
        if decision not in {"ALLOW", "BLOCK", "UNKNOWN"}:
            decision = "UNKNOWN"
        out: dict[str, Any] = {
            "WOULD_BLOCK": bool(would_block),
            "REASON": str(reason),
            "SHADOW_DECISION": decision,
        }
        if extra:
            out.update(extra)
        return out

    ctx = dict(context or {})
    if variant_id == VARIANT_C0:
        return _pack(
            would_block=False,
            reason="BASELINE_ALLOW",
            shadow_decision="ALLOW",
        )
    if variant_id == VARIANT_C1:
        block = delay_seconds < 60.0
        return _pack(
            would_block=block,
            reason="COOLDOWN_60S" if block else "COOLDOWN_ELAPSED",
            shadow_decision="BLOCK" if block else "ALLOW",
        )
    if variant_id == VARIANT_C2:
        block = delay_seconds < 180.0
        return _pack(
            would_block=block,
            reason="COOLDOWN_180S" if block else "COOLDOWN_ELAPSED",
            shadow_decision="BLOCK" if block else "ALLOW",
        )
    if variant_id == VARIANT_C3:
        if delay_seconds < 180.0:
            return _pack(
                would_block=True,
                reason="CONTEXTUAL_COOLDOWN_180S",
                shadow_decision="BLOCK",
            )
        # contextual confirmation — UNKNOWN이면 날조하지 않고 구분 기록
        flags = {
            "new_signal": _tri_flag(ctx, "new_signal", "fresh_signal"),
            "ma_improved": _tri_flag(ctx, "ma_improved", "MA_RECOVERED"),
            "momentum_reset": _tri_flag(ctx, "momentum_reset"),
            "score_improved": _tri_flag(ctx, "score_improved"),
        }
        if any(v is True for v in flags.values()):
            return _pack(
                would_block=False,
                reason="CONTEXTUAL_CONFIRMED",
                shadow_decision="ALLOW",
                extra={"FLAGS": flags},
            )
        if all(v is False for v in flags.values()):
            return _pack(
                would_block=True,
                reason="NO_INDEPENDENT_CONFIRMATION",
                shadow_decision="BLOCK",
                extra={"FLAGS": flags},
            )
        # 일부/전부 UNKNOWN → SHADOW_DECISION=UNKNOWN (NULL 금지)
        return _pack(
            would_block=True,
            reason="CONTEXTUAL_CONFIRMATION_UNKNOWN",
            shadow_decision="UNKNOWN",
            extra={"FLAGS": flags},
        )
    return _pack(
        would_block=False,
        reason="UNKNOWN_VARIANT",
        shadow_decision="UNKNOWN",
    )
