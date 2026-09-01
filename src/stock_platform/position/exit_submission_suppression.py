"""Exit monitor submit suppression — deterministic LIVE/ARM blocker spam 방지.

Exit condition evaluation 은 유지; 동일 blocker generation 내 repeat submit 만 억제.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# LIVE/ARM fail-closed 등 deterministic blocker (policy 변경 없음)
DETERMINISTIC_EXIT_BLOCKERS = frozenset(
    {
        "LIVE_ORDER_DISABLED",
        "LIVE_ARM_EXPIRED",
        "ARM_TOKEN_REJECT",
        "LIVE_NOT_ARMED",
        "ACTIVATION_INACTIVE",
    }
)

_suppressed_attempts: int = 0
_last_suppression: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ExitSubmitSuppressionDecision:
    suppress: bool
    blocker_code: str | None = None
    suppression_key: str | None = None
    reason: str | None = None


def uba_safety_generation(
    *,
    live_order_enabled: bool,
    live_armed: bool,
    arm_expires_at: datetime | None,
) -> str:
    exp = (
        arm_expires_at.astimezone(timezone.utc).isoformat()
        if arm_expires_at is not None
        else "none"
    )
    return f"live={int(bool(live_order_enabled))}|arm={int(bool(live_armed))}|exp={exp}"


def predict_deterministic_exit_blocker(
    *,
    live_order_enabled: bool,
    live_armed: bool,
    arm_expires_at: datetime | None,
    now: datetime | None = None,
) -> str | None:
    """LiveSafetyPipeline step-2/2b 와 정렬된 사전 blocker 예측 (submit 전)."""

    if not bool(live_order_enabled):
        return "LIVE_ORDER_DISABLED"
    if not bool(live_armed):
        return "LIVE_ARM_EXPIRED"
    if arm_expires_at is not None:
        ref = now or datetime.now(timezone.utc)
        exp = arm_expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= ref.astimezone(timezone.utc):
            return "LIVE_ARM_EXPIRED"
    return None


def should_suppress_exit_submit(
    *,
    user_broker_account_id: int,
    symbol: str,
    binding_id: int | None,
    exit_reason: str,
    blocker_code: str,
    live_order_enabled: bool,
    live_armed: bool,
    arm_expires_at: datetime | None,
) -> ExitSubmitSuppressionDecision:
    """동일 blocker generation 내 repeat submit 억제."""

    global _suppressed_attempts, _last_suppression

    if blocker_code not in DETERMINISTIC_EXIT_BLOCKERS:
        return ExitSubmitSuppressionDecision(
            suppress=False, blocker_code=blocker_code
        )

    gen = uba_safety_generation(
        live_order_enabled=live_order_enabled,
        live_armed=live_armed,
        arm_expires_at=arm_expires_at,
    )
    key = (
        f"{int(user_broker_account_id)}|{gen}|"
        f"{symbol.upper()}|{binding_id or 0}|"
        f"{exit_reason}|{blocker_code}"
    )

    if not hasattr(should_suppress_exit_submit, "_seen"):
        should_suppress_exit_submit._seen = set()  # type: ignore[attr-defined]

    seen: set[str] = should_suppress_exit_submit._seen  # type: ignore[attr-defined]
    if key in seen:
        _suppressed_attempts += 1
        _last_suppression = {
            "key": key,
            "blocker_code": blocker_code,
            "symbol": symbol,
            "exit_reason": exit_reason,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        return ExitSubmitSuppressionDecision(
            suppress=True,
            blocker_code=blocker_code,
            suppression_key=key,
            reason="DETERMINISTIC_BLOCKER_REPEAT",
        )

    seen.add(key)
    # generation 변경 시 stale key 정리
    prefix = f"{int(user_broker_account_id)}|{gen}|"
    stale = [k for k in seen if k.startswith(f"{int(user_broker_account_id)}|") and not k.startswith(prefix)]
    for k in stale:
        seen.discard(k)

    return ExitSubmitSuppressionDecision(
        suppress=False, blocker_code=blocker_code, suppression_key=key
    )


def reset_exit_suppression_for_uba(user_broker_account_id: int) -> None:
    """테스트/명시 reset."""

    if not hasattr(should_suppress_exit_submit, "_seen"):
        return
    seen: set[str] = should_suppress_exit_submit._seen  # type: ignore[attr-defined]
    prefix = f"{int(user_broker_account_id)}|"
    for k in list(seen):
        if k.startswith(prefix):
            seen.discard(k)


def exit_suppression_status() -> dict[str, Any]:
    return {
        "EXIT_SUBMISSION_SUPPRESSED": _suppressed_attempts,
        "EXIT_SUPPRESSION_REASON": (
            (_last_suppression or {}).get("blocker_code")
        ),
        "last_suppression": _last_suppression,
    }
