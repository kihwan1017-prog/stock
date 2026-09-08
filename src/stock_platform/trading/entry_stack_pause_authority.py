"""ENTRY stack pause authority — explicit PAUSE는 auto-restore/resume 금지.

Scheduler PAUSE 또는 scoped runtime explicit pause 가 있으면
Kiwoom ENTRY(runtime/runner) 자동 부활을 fail-closed 한다.
UBA1380(Upbit) restore 경로에는 사용하지 않는다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.runtime_manager import (
    RuntimeLifecycleStatus,
    dynamic_strategy_runtime_manager,
)
from stock_platform.trading.trading_scheduler_control import (
    get_trading_scheduler_desired_state,
)

# 운영자/안전/정비 — auto-resume 금지
EXPLICIT_PAUSE_REASONS = frozenset(
    {
        "OPERATOR_PAUSE",
        "SAFETY_PAUSE",
        "MAINTENANCE_PAUSE",
        "AUTO_RECOVERY_PAUSE",
        "admin_pause",
        "manual_review_required",
        "UPBIT_REMOTE_ONLY_ORDER_REVIEW",
        "recovery_failed",
        "credential_error",
        "kill_switch",
    }
)

EXPLICIT_PAUSE_PREFIXES = (
    "OPERATOR_",
    "SAFETY_",
    "MAINTENANCE_",
)

# crash/reload 후 desired RUN 복구는 허용
RESUMABLE_PAUSE_REASONS = frozenset(
    {
        "reloaded_paused",
        "shutdown",
        "stopped",
    }
)


def is_explicit_entry_pause_reason(reason: str | None) -> bool:
    """운영자/안전 의도 PAUSE 여부."""

    if reason is None:
        return False
    text = str(reason).strip()
    if not text:
        return False
    if text in RESUMABLE_PAUSE_REASONS:
        return False
    if text in EXPLICIT_PAUSE_REASONS:
        return True
    upper = text.upper()
    if upper.startswith(EXPLICIT_PAUSE_PREFIXES):
        return True
    # 정렬/안전 작업 계열 (예: KIWOOM_UBA1381_POST_SMOKE_...)
    if "POST_SMOKE" in upper or "RUNTIME_STATE_ALIGNMENT" in upper:
        return True
    if "SAFETELY_PAUSED" in upper or "OPERATOR" in upper:
        return True
    # admin API 기본값 외 자유 문자열도 PAUSED면 의도적 pause 로 취급
    # (crash 복구는 STOPPED/missing 경로)
    return True


def trading_scheduler_entry_hold() -> dict[str, Any]:
    """전역 Trading Scheduler desired=PAUSE 이면 Kiwoom ENTRY hold."""

    desired = str(get_trading_scheduler_desired_state() or "").upper()
    hold = desired == "PAUSE"
    return {
        "hold": hold,
        "scheduler_desired": desired,
        "reason": "SCHEDULER_DESIRED_PAUSE" if hold else None,
    }


def scoped_runtime_explicit_pause_hold(
    *,
    user_broker_account_id: int,
    broker_code: str = "KIWOOM",
    strategy_id: int | None = None,
) -> dict[str, Any]:
    """해당 UBA scoped runtime이 explicit PAUSED 이면 hold."""

    uba_id = int(user_broker_account_id)
    broker_u = str(broker_code or "").upper()
    entries = dynamic_strategy_runtime_manager.list_entries(
        user_broker_account_id=uba_id,
        strategy_id=int(strategy_id) if strategy_id is not None else None,
    )
    held: list[dict[str, Any]] = []
    for entry in entries:
        if str(entry.scope.broker_code or "").upper() != broker_u:
            continue
        if entry.status != RuntimeLifecycleStatus.PAUSED:
            continue
        reason = entry.pause_reason
        if not is_explicit_entry_pause_reason(reason):
            continue
        held.append(
            {
                "scope_key": entry.scope.scope_key,
                "pause_reason": reason,
                "status": entry.status.value,
            }
        )
    return {
        "hold": bool(held),
        "paused_entries": held,
        "reason": "EXPLICIT_SCOPED_RUNTIME_PAUSE" if held else None,
    }


def evaluate_kiwoom_entry_stack_hold(
    session: Session | None = None,
    *,
    user_broker_account_id: int,
    strategy_id: int | None = None,
) -> dict[str, Any]:
    """Kiwoom ENTRY auto-restore/resume 금지 여부.

    session 은 향후 DB pause provenance 확장용 (현재 unused).
    """

    _ = session  # reserved
    sched = trading_scheduler_entry_hold()
    scoped = scoped_runtime_explicit_pause_hold(
        user_broker_account_id=int(user_broker_account_id),
        broker_code="KIWOOM",
        strategy_id=strategy_id,
    )
    hold = bool(sched.get("hold") or scoped.get("hold"))
    reasons: list[str] = []
    if sched.get("reason"):
        reasons.append(str(sched["reason"]))
    if scoped.get("reason"):
        reasons.append(str(scoped["reason"]))
    return {
        "hold": hold,
        "reasons": reasons,
        "scheduler": sched,
        "scoped_runtime": scoped,
        "entry_components": ("runtime", "runner"),
    }


__all__ = [
    "EXPLICIT_PAUSE_REASONS",
    "evaluate_kiwoom_entry_stack_hold",
    "is_explicit_entry_pause_reason",
    "scoped_runtime_explicit_pause_hold",
    "trading_scheduler_entry_hold",
]
