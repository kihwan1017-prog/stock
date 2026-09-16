"""STEP 11-13 — Lifecycle status transition rules."""

from __future__ import annotations

from stock_platform.ai.candidate_lifecycle.constants import ALLOWED_TRANSITIONS


def can_transition(from_status: str, to_status: str) -> bool:
    """lifecycle_status 전이 허용 여부."""
    allowed = ALLOWED_TRANSITIONS.get(from_status)
    if allowed is None:
        return False
    return to_status in allowed
