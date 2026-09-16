"""STEP 11-13 — Health status computation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stock_platform.ai.candidate_lifecycle.constants import (
    HEALTH_PRIORITY,
    HEALTH_VERSION,
)
from stock_platform.ai.candidate_lifecycle.expiration import is_expired


def compute_health(
    lifecycle_row: Any,
    *,
    now: datetime | None = None,
    stale: bool = False,
    has_warnings: bool = False,
) -> str:
    """
    health_status 결정.

    우선순위: REVOKED > SUPERSEDED > EXPIRED > REVALIDATION_REQUIRED >
              STALE > WARNING > HEALTHY > UNKNOWN
    """
    check_time = now or datetime.now(timezone.utc)
    candidates: set[str] = set()

    lifecycle_status = getattr(lifecycle_row, "lifecycle_status", None)
    if lifecycle_status == "REVOKED" or getattr(lifecycle_row, "revoked_at", None):
        candidates.add("REVOKED")
    if lifecycle_status == "SUPERSEDED" or getattr(
        lifecycle_row, "superseded_at", None
    ):
        candidates.add("SUPERSEDED")

    expiration_at = getattr(lifecycle_row, "expiration_at", None)
    expired_at = getattr(lifecycle_row, "expired_at", None)
    if lifecycle_status == "EXPIRED" or expired_at is not None:
        candidates.add("EXPIRED")
    elif expiration_at is not None and is_expired(
        expires_at=expiration_at, now=check_time
    ):
        candidates.add("EXPIRED")

    if getattr(lifecycle_row, "revalidation_required", False):
        candidates.add("REVALIDATION_REQUIRED")
    if getattr(lifecycle_row, "source_changed", False):
        candidates.add("REVALIDATION_REQUIRED")

    if stale:
        candidates.add("STALE")
    if has_warnings:
        candidates.add("WARNING")

    source_fp = getattr(lifecycle_row, "source_fingerprint", None)
    if source_fp and not candidates.intersection(
        {"REVOKED", "SUPERSEDED", "EXPIRED", "REVALIDATION_REQUIRED", "STALE"}
    ):
        if has_warnings:
            pass  # WARNING already added
        else:
            candidates.add("HEALTHY")

    if not candidates:
        candidates.add("UNKNOWN")

    for status in HEALTH_PRIORITY:
        if status in candidates:
            return status

    return "UNKNOWN"


def health_metadata() -> dict[str, str]:
    return {"health_version": HEALTH_VERSION}
