"""Activation session TTL ↔ unattended authorization horizon alignment.

Horizon auto-renew must not extend authorized_until without refreshing eligible
ACTIVE activation TTL (fail-closed; no revive of EXPIRED/REVOKED/DISABLED).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from stock_platform.broker.live_transition_entities import (
    LiveTradingTransitionEntity,
)
from stock_platform.common.settings import LIVE_ACTIVATION_TTL_HOURS_MAX
from stock_platform.trading.live_session_expiry import (
    aware_utc,
    is_activation_due,
)

_INELIGIBLE_STATUSES = frozenset({"EXPIRED", "REVOKED", "DISABLED"})

ACTIVATION_HORIZON_MISMATCH = "ACTIVATION_HORIZON_MISMATCH"


def activation_horizon_mismatch_margin_seconds(
    *,
    renewal_margin_seconds: int,
    arm_lease_ttl_seconds: int,
) -> int:
    """ARM renew margin과 동일한 canonical window."""

    return max(
        int(renewal_margin_seconds),
        max(60, int(arm_lease_ttl_seconds) // 4),
    )


def compute_activation_horizon_gap_seconds(
    *,
    authorized_until: datetime | None,
    activation_expires_at: datetime | None,
) -> int | None:
    """authorized_until - activation_expires_at (양수 = activation이 먼저 만료)."""

    auth = aware_utc(authorized_until)
    act = aware_utc(activation_expires_at)
    if auth is None or act is None:
        return None
    return int((auth - act).total_seconds())


def is_activation_eligible_for_horizon_refresh(
    entity: LiveTradingTransitionEntity | None,
    *,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """ACTIVE·미만료만 refresh 가능 — EXPIRED/REVOKED/DISABLED 자동 부활 금지."""

    if entity is None:
        return False, "NO_ACTIVE_ACTIVATION"
    if not bool(entity.enabled):
        return False, "DISABLED"
    status = str(entity.activation_status or "").upper()
    if status in _INELIGIBLE_STATUSES:
        return False, status
    if is_activation_due(entity, now=now):
        return False, "EXPIRED"
    return True, "OK"


def compute_horizon_activation_refresh_hours(
    *,
    authorized_until: datetime,
    activation_renew_hours: int,
    now: datetime,
) -> int:
    """successor TTL — authorized_until 및 max cap을 초과하지 않음."""

    auth = aware_utc(authorized_until)
    current = aware_utc(now) or datetime.now(timezone.utc)
    if auth is None:
        raise ValueError("authorized_until required")
    hours_to_horizon = max(1, int((auth - current).total_seconds() // 3600))
    return max(
        1,
        min(
            int(activation_renew_hours),
            hours_to_horizon,
            int(LIVE_ACTIVATION_TTL_HOURS_MAX),
        ),
    )


def activation_horizon_alignment_status(
    *,
    authorized_until: datetime | None,
    activation_expires_at: datetime | None,
    mismatch_margin_seconds: int,
) -> dict[str, Any]:
    """ops-status / mismatch alert용 정렬 상태."""

    gap = compute_activation_horizon_gap_seconds(
        authorized_until=authorized_until,
        activation_expires_at=activation_expires_at,
    )
    if gap is None:
        return {
            "ACTIVATION_HORIZON_ALIGNED": True,
            "ACTIVATION_HORIZON_DELTA_SECONDS": None,
            "ACTIVATION_HORIZON_GAP_SECONDS": None,
        }
    aligned = gap <= int(mismatch_margin_seconds)
    return {
        "ACTIVATION_HORIZON_ALIGNED": aligned,
        # delta: activation_expires_at - authorized_until (음수 = activation 먼저 만료)
        "ACTIVATION_HORIZON_DELTA_SECONDS": -gap,
        "ACTIVATION_HORIZON_GAP_SECONDS": gap,
    }


def activation_refresh_needed_for_horizon(
    *,
    authorized_until: datetime,
    activation_expires_at: datetime,
    mismatch_margin_seconds: int,
) -> bool:
    """horizon 연장 후 activation이 margin 내에 있지 않으면 refresh 필요."""

    gap = compute_activation_horizon_gap_seconds(
        authorized_until=authorized_until,
        activation_expires_at=activation_expires_at,
    )
    if gap is None:
        return True
    return gap > int(mismatch_margin_seconds)


def projected_successor_expires_at(
    *,
    now: datetime,
    renew_hours: int,
    authorized_until: datetime,
) -> datetime:
    """ACTIVATION_EXPIRES_AT <= AUTHORIZED_UNTIL invariant."""

    current = aware_utc(now) or datetime.now(timezone.utc)
    auth = aware_utc(authorized_until)
    if auth is None:
        raise ValueError("authorized_until required")
    projected = current + timedelta(hours=int(renew_hours))
    if projected > auth:
        return auth
    return projected
