"""STEP 8-11 — Overall / Risk 상태 판정 (Backend 단일 기준)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


ZERO = Decimal("0")


def daily_loss_usage_status(
    *,
    current_loss: Decimal,
    limit_amount: Decimal,
) -> str:
    """NORMAL / WARNING / DANGER / BLOCKED."""

    if limit_amount <= ZERO:
        return "UNKNOWN"
    ratio = current_loss / limit_amount
    if ratio >= Decimal("1"):
        return "BLOCKED"
    if ratio >= Decimal("0.90"):
        return "DANGER"
    if ratio >= Decimal("0.70"):
        return "WARNING"
    return "NORMAL"


def compute_overall_status(signals: dict[str, Any]) -> str:
    """
    우선순위: ERROR > WARNING > HEALTHY.
    Frontend에서 재계산하지 않도록 Backend만 사용.
    """

    errors = list(signals.get("errors") or [])
    warnings = list(signals.get("warnings") or [])
    if errors:
        return "ERROR"
    if warnings:
        return "WARNING"
    return "HEALTHY"
