"""No-trade classification — 거래 건수가 아닌 pipeline progression 기준."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def classify_no_trade_status(
    *,
    health_state: str,
    partial_restore: bool,
    stack_components_down: bool,
    daily_blocking: bool,
    free_slots: int,
    waiting_count: int,
    max_positions: int = 5,
    selection_count_window: int,
    candidate_count_window: int,
    order_count_window: int,
    admission_count_window: int = 0,
    feed_healthy: bool,
    scanner_active: bool,
    pipeline_stall_minutes: float,
    last_order_at: datetime | None,
    last_selection_at: datetime | None,
    waiting_slot_starvation: bool = False,
    starvation_escalation: str = "NONE",
    oldest_waiting_age_seconds: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """NORMAL_NO_SIGNAL | NORMAL_POLICY_BLOCK | WAITING_SLOT_STARVATION | PIPELINE_STALL | SYSTEM_FAILURE."""

    now = now or datetime.now(timezone.utc)
    classification = "UNKNOWN"
    detail: dict[str, Any] = {}

    if partial_restore or stack_components_down:
        classification = "SYSTEM_FAILURE"
        detail["reason"] = "EXECUTION_STACK_OR_PARTIAL_RESTORE"
    elif waiting_slot_starvation:
        if starvation_escalation == "BROKEN":
            classification = "PIPELINE_STALL"
            detail["reason"] = "WAITING_SLOT_STARVATION"
            detail["first_stalled_transition"] = "WAITING_TO_ADMISSION"
        else:
            classification = "WAITING_SLOT_STARVATION"
            detail["reason"] = "ALL_SLOTS_WAITING_NO_ENTRY_PROGRESS"
        if oldest_waiting_age_seconds is not None:
            detail["oldest_waiting_age_seconds"] = round(
                oldest_waiting_age_seconds, 1
            )
    elif health_state == "BROKEN":
        classification = "SYSTEM_FAILURE"
        detail["reason"] = "HEALTH_BROKEN"
    elif daily_blocking:
        classification = "NORMAL_POLICY_BLOCK"
        detail["reason"] = "DAILY_LIMIT"
    elif free_slots <= 0 and waiting_count > 0 and order_count_window == 0:
        classification = "NORMAL_POLICY_BLOCK"
        detail["reason"] = "SLOT_FULL_WAITING"
    elif (
        feed_healthy
        and scanner_active
        and candidate_count_window == 0
        and selection_count_window == 0
        and order_count_window == 0
    ):
        classification = "NORMAL_NO_SIGNAL"
        detail["reason"] = "NO_CANDIDATES_OR_SIGNALS"
    else:
        stall_ref = last_order_at or last_selection_at
        stalled = False
        if stall_ref is not None:
            stalled = (now - stall_ref).total_seconds() > pipeline_stall_minutes * 60
        elif selection_count_window > 0 or waiting_count > 0:
            stalled = True

        has_pipeline_activity = (
            selection_count_window > 0
            or waiting_count > 0
            or candidate_count_window > 0
        )
        if (
            has_pipeline_activity
            and not daily_blocking
            and order_count_window == 0
            and admission_count_window == 0
            and stalled
            and health_state in {"READY", "DEGRADED"}
        ):
            classification = "PIPELINE_STALL"
            detail["reason"] = "WAITING_OR_SELECTION_WITHOUT_ORDER_PROGRESS"
            if waiting_count > 0:
                detail["first_stalled_transition"] = "WAITING_TO_ADMISSION"
        elif order_count_window == 0 and not stack_components_down:
            if candidate_count_window == 0:
                classification = "NORMAL_NO_SIGNAL"
            elif waiting_count > 0 and admission_count_window == 0:
                if free_slots <= 0:
                    classification = "NORMAL_POLICY_BLOCK"
                    detail["reason"] = "SLOT_FULL_WAITING"
                else:
                    classification = "PIPELINE_STALL"
                    detail["reason"] = "WAITING_WITHOUT_ADMISSION"
                    detail["first_stalled_transition"] = "WAITING_TO_ADMISSION"
            else:
                classification = "NORMAL_NO_SIGNAL"

    return {
        "classification": classification,
        "detail": detail,
        "evaluated_at": now.isoformat(),
    }
