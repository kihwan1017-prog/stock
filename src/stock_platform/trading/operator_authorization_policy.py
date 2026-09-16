"""Operator Authorization policy — Upbit 24H ops lease SoT.

Canonical SoT: operation.live_unattended_authorization
(= LiveUnattendedAuthorizationEntity / Unattended lease).

계층:
  OPERATOR AUTHORIZATION (unattended lease horizon)
        ↓
  ACTIVATION (live_trading_transition)
        ↓
  ARM
        ↓
  LIVE EXECUTION

Invariant:
  ARM_EXPIRES_AT <= ACTIVATION_EXPIRES_AT - SAFETY_MARGIN
  ACTIVATION_EXPIRES_AT <= AUTHORIZATION_EXPIRES_AT
  UNATTENDED/AUTHORIZATION 동일 SoT → UNATTENDED_EXPIRES_AT == AUTHORIZATION_EXPIRES_AT

Authorization 만료 + 오픈 포지션:
  AUTH_EXPIRY_EXISTING_POSITION_POLICY = PROTECTIVE_EXIT_ONLY
  (ENTRY OFF, protective EXIT/LIVE·ARM 유지 — 기존 unattended _fail_closed_on_expiry)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# UPBIT HOURS_24 명시 승인기간 (무기한 금지)
OPERATOR_AUTHORIZATION_ALLOWED_HOURS: tuple[int, ...] = (24, 48, 72)
OPERATOR_AUTHORIZATION_MAX_HOURS = 72
ARM_SAFETY_MARGIN_SECONDS_DEFAULT = 60

# Authorization 만료 시 기존 포지션 정책 (현행 SoT 문서화)
AUTH_EXPIRY_EXISTING_POSITION_POLICY = "PROTECTIVE_EXIT_ONLY"
# 포지션 없으면 FAIL_CLOSED_FULL (LIVE/ARM OFF)
AUTH_EXPIRY_NO_POSITION_POLICY = "FAIL_CLOSED_FULL"


def validate_operator_authorization_hours(
    hours: int | None,
    *,
    allowed: tuple[int, ...] = OPERATOR_AUTHORIZATION_ALLOWED_HOURS,
) -> int:
    """명시 승인기간만 허용. 무기한/임의 값 거부."""

    if hours is None:
        return 24
    value = int(hours)
    if value not in allowed:
        raise ValueError(
            f"OPERATOR_AUTHORIZATION_HOURS_INVALID:"
            f"allowed={list(allowed)} got={value}"
        )
    return value


def authorization_active_from_unattended(unattended: dict[str, Any] | None) -> bool:
    """ops/status unattended 블록 → Operator Authorization ACTIVE 판정.

    Unattended execution OFF 여도 status_code=ACTIVE + remaining>0 이면 Auth ACTIVE.
    """

    if not isinstance(unattended, dict):
        return False
    if bool(unattended.get("operator_authorization_active")):
        return True
    status = str(unattended.get("status_code") or "").upper()
    remaining = int(unattended.get("remaining_seconds") or 0)
    if status == "ACTIVE" and remaining > 0:
        return True
    if status in {"PROTECTIVE", "PROTECTIVE_EXIT_ONLY"}:
        return True
    if bool(unattended.get("unattended_enabled")) or bool(
        unattended.get("entry_lease_active")
    ):
        return True
    return status in {"ON", "ENABLED"}


def build_operator_authorization_view(
    unattended: dict[str, Any] | None,
    *,
    activation_expires_at: str | None = None,
    arm_expires_at: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Admin/ops UI용 Operator Authorization 요약 (SoT=unattended)."""

    u = unattended if isinstance(unattended, dict) else {}
    active = authorization_active_from_unattended(u)
    remaining = int(u.get("remaining_seconds") or 0)
    auth_until = u.get("authorized_until")
    return {
        "schema": "operator_authorization_v1",
        "sot": "operation.live_unattended_authorization",
        "authorization_id": u.get("authorization_id"),
        "status": "ACTIVE" if active else str(u.get("status_code") or "OFF"),
        "active": active,
        "approved_by": u.get("approved_by"),
        "approved_at": u.get("approved_at"),
        "valid_until": auth_until,
        "remaining_seconds": remaining,
        "authorization_mode": u.get("authorization_mode"),
        "auto_renew_enabled": bool(u.get("auto_renew_enabled")),
        "lease_auto_renew_enabled": bool(
            u.get("lease_auto_renew_enabled", u.get("auto_renew_enabled"))
        ),
        "operator_authorization_auto_extend": bool(
            u.get("operator_authorization_auto_extend")
        ),
        "operator_authorization_auto_extend_supported": bool(
            u.get("operator_authorization_auto_extend_supported")
        ),
        "renewal_status": (
            "AUTH_AND_LEASE_AUTO_RENEW_ON"
            if active
            and bool(u.get("auto_renew_enabled"))
            and bool(u.get("operator_authorization_auto_extend_supported"))
            else (
                "LEASE_AUTO_RENEW_ON"
                if active and bool(u.get("auto_renew_enabled"))
                else ("ACTIVE_MANUAL" if active else "OFF")
            )
        ),
        "next_authorization_expiry_warning_at": u.get(
            "next_authorization_expiry_warning_at"
        )
        or u.get("next_horizon_renew_check_at"),
        "authorization_expiring_soon": bool(
            u.get("authorization_expiring_soon")
        )
        or (active and 0 < remaining <= 3600),
        "last_horizon_auto_renew": u.get("last_horizon_auto_renew"),
        "activation_expires_at": activation_expires_at,
        "arm_expires_at": arm_expires_at,
        "allowed_duration_hours": list(OPERATOR_AUTHORIZATION_ALLOWED_HOURS),
        "max_duration_hours": OPERATOR_AUTHORIZATION_MAX_HOURS,
        "arm_safety_margin_seconds": ARM_SAFETY_MARGIN_SECONDS_DEFAULT,
        "auth_expiry_existing_position_policy": AUTH_EXPIRY_EXISTING_POSITION_POLICY,
        "auth_expiry_no_position_policy": AUTH_EXPIRY_NO_POSITION_POLICY,
        "expiring_soon": active and 0 < remaining <= 3600,
        "as_of": (now or datetime.now(timezone.utc)).isoformat(),
    }


def assert_lease_invariants(
    *,
    authorization_expires_at: datetime | None,
    activation_expires_at: datetime | None,
    arm_expires_at: datetime | None,
    safety_margin_seconds: int = ARM_SAFETY_MARGIN_SECONDS_DEFAULT,
) -> dict[str, Any]:
    """Invariant 검사 — 위반 시 ok=False (호출측 fail-closed)."""

    issues: list[str] = []
    if (
        activation_expires_at is not None
        and authorization_expires_at is not None
        and activation_expires_at > authorization_expires_at
    ):
        issues.append("ACTIVATION_EXCEEDS_AUTHORIZATION")
    if arm_expires_at is not None and activation_expires_at is not None:
        limit = activation_expires_at - timedelta(seconds=int(safety_margin_seconds))
        if arm_expires_at > activation_expires_at:
            issues.append("ARM_EXCEEDS_ACTIVATION")
        elif arm_expires_at > limit:
            issues.append("ARM_MARGIN_VIOLATION")
    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "ACTIVATION_LE_AUTHORIZATION": "ACTIVATION_EXCEEDS_AUTHORIZATION"
        not in issues,
        "ARM_LE_ACTIVATION": "ARM_EXCEEDS_ACTIVATION" not in issues,
        "ARM_MARGIN_OK": "ARM_MARGIN_VIOLATION" not in issues,
        "safety_margin_seconds": int(safety_margin_seconds),
    }
