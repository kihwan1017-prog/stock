"""STEP 11-11 — Queue expiration policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stock_platform.ai.candidate_recommendation_queue.constants import (
    CRYPTO_DEFAULT_EXPIRY_HOURS,
    CRYPTO_MAX_EXPIRY_HOURS,
    KRX_DEFAULT_EXPIRY_HOURS,
    KRX_MAX_EXPIRY_HOURS,
)


def compute_expires_at(
    *,
    market_type: str,
    base_time: datetime | None = None,
    requested_hours: float | None = None,
) -> datetime:
    """
    만료 시각 계산.

    - KRX(STOCK): 기본 24h, 최대 72h
    - CRYPTO: 기본 12h, 최대 48h
    """
    now = base_time or datetime.now(timezone.utc)
    if market_type == "CRYPTO":
        default_hours = CRYPTO_DEFAULT_EXPIRY_HOURS
        max_hours = CRYPTO_MAX_EXPIRY_HOURS
    else:
        default_hours = KRX_DEFAULT_EXPIRY_HOURS
        max_hours = KRX_MAX_EXPIRY_HOURS

    hours = requested_hours if requested_hours is not None else default_hours
    hours = min(max(float(hours), 1.0), float(max_hours))
    return now + timedelta(hours=hours)


def is_expired(*, expires_at: datetime, now: datetime | None = None) -> bool:
    check_time = now or datetime.now(timezone.utc)
    exp = expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return check_time >= exp
