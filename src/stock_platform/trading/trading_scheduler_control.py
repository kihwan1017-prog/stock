"""Trading Scheduler Desired State — Scheduler와 Runtime/ARM 분리 제어."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# 프로세스 메모리 — 기본 PAUSE (Fail Closed)
_DESIRED_STATE: str = "PAUSE"
_META: dict[str, Any] = {
    "updated_at": None,
    "actor": None,
    "reason": None,
    "correlation_id": None,
    "started_at": None,
    "paused_at": None,
}
_TICK_COUNT: int = 0
_LAST_TICK_AT: str | None = None


def get_trading_scheduler_desired_state() -> str:
    return _DESIRED_STATE


def get_trading_scheduler_control_meta() -> dict[str, Any]:
    return {
        "desired_state": _DESIRED_STATE,
        **dict(_META),
        "tick_count": _TICK_COUNT,
        "last_tick_at": _LAST_TICK_AT,
    }


def set_trading_scheduler_desired_state(
    state: str,
    *,
    actor: str | None = None,
    reason: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    global _DESIRED_STATE, _META
    normalized = (state or "").strip().upper()
    if normalized in {"RUN", "RUNNING", "START"}:
        normalized = "RUN"
    elif normalized in {"PAUSE", "PAUSED", "STOP", "STOPPED"}:
        normalized = "PAUSE"
    else:
        raise ValueError(f"invalid trading scheduler desired state: {state}")

    now = datetime.now(timezone.utc).isoformat()
    _DESIRED_STATE = normalized
    _META = {
        **_META,
        "updated_at": now,
        "actor": actor,
        "reason": reason,
        "correlation_id": correlation_id,
    }
    if normalized == "RUN":
        _META["started_at"] = now
    else:
        _META["paused_at"] = now
    return get_trading_scheduler_control_meta()


def record_trading_scheduler_tick() -> None:
    global _TICK_COUNT, _LAST_TICK_AT
    _TICK_COUNT += 1
    _LAST_TICK_AT = datetime.now(timezone.utc).isoformat()


def reset_trading_scheduler_control_for_tests() -> None:
    """단위 테스트 전용."""
    global _DESIRED_STATE, _META, _TICK_COUNT, _LAST_TICK_AT
    _DESIRED_STATE = "PAUSE"
    _META = {
        "updated_at": None,
        "actor": None,
        "reason": None,
        "correlation_id": None,
        "started_at": None,
        "paused_at": None,
        "persisted": False,
        "version": None,
        "blocked_reason": None,
        "startup_restore_attempted": False,
        "startup_restore_result": None,
        "restored_on_startup": False,
    }
    _TICK_COUNT = 0
    _LAST_TICK_AT = None


def hydrate_trading_scheduler_control(
    *,
    desired_state: str,
    actor: str | None = None,
    reason: str | None = None,
    correlation_id: str | None = None,
    updated_at: str | None = None,
    version: int | None = None,
    persisted: bool = True,
    blocked_reason: str | None = None,
    startup_restore_attempted: bool | None = None,
    startup_restore_result: str | None = None,
    restored_on_startup: bool | None = None,
    started_at: str | None = None,
    paused_at: str | None = None,
) -> None:
    """DB에서 로드한 값을 프로세스 캐시에 반영."""

    global _DESIRED_STATE, _META
    normalized = (desired_state or "PAUSE").strip().upper()
    if normalized in {"RUN", "RUNNING", "START"}:
        normalized = "RUN"
    else:
        normalized = "PAUSE"
    _DESIRED_STATE = normalized
    _META = {
        **_META,
        "updated_at": updated_at,
        "actor": actor,
        "reason": reason,
        "correlation_id": correlation_id,
        "persisted": persisted,
        "version": version,
        "blocked_reason": blocked_reason,
        "startup_restore_attempted": startup_restore_attempted,
        "startup_restore_result": startup_restore_result,
        "restored_on_startup": restored_on_startup,
    }
    if started_at is not None:
        _META["started_at"] = started_at
    if paused_at is not None:
        _META["paused_at"] = paused_at
