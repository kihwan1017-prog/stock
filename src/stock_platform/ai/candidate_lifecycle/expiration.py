"""STEP 11-13 — Lifecycle expiration policy.

KRX: commit + 7 calendar days (거래일 캘린더 미적용 — UTC 저장).
CRYPTO: commit + 48 hours.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stock_platform.ai.candidate_lifecycle.constants import (
    CRYPTO_EXPIRY_HOURS,
    KRX_EXPIRY_CALENDAR_DAYS,
)


def compute_expiration_at(
    *,
    market_type: str,
    committed_at: datetime,
) -> datetime:
    """
    Promotion commit 시각 기준 만료 시각 (UTC).

    KRX는 calendar day +7 (KRX 거래일 캘린더 미반영 — 운영 문서 참조).
    """
    base = committed_at
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)

    if market_type == "CRYPTO":
        return base + timedelta(hours=CRYPTO_EXPIRY_HOURS)
    return base + timedelta(days=KRX_EXPIRY_CALENDAR_DAYS)


def is_expired(*, expires_at: datetime, now: datetime | None = None) -> bool:
    check_time = now or datetime.now(timezone.utc)
    exp = expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return check_time >= exp
