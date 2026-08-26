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
    selection_count_window: int,
    candidate_count_window: int,
    order_count_window: int,
    feed_healthy: bool,
    scanner_active: bool,
    pipeline_stall_minutes: float,
    last_order_at: datetime | None,
    last_selection_at: datetime | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """NORMAL_NO_SIGNAL | NORMAL_POLICY_BLOCK | PIPELINE_STALL | SYSTEM_FAILURE."""

    now = now or datetime.now(timezone.utc)
    classification = "UNKNOWN"
    detail: dict[str, Any] = {}

    if partial_restore or stack_components_down or health_state == "BROKEN":
        classification = "SYSTEM_FAILURE"
        detail["reason"] = "EXECUTION_STACK_OR_PARTIAL_RESTORE"
    elif daily_blocking:
        classification = "NORMAL_POLICY_BLOCK"
        detail["reason"] = "DAILY_LIMIT"
    elif free_slots <= 0 and waiting_count >= 5 and order_count_window == 0:
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

        if (
            (selection_count_window > 0 or waiting_count > 0)
            and not daily_blocking
            and free_slots > 0 or waiting_count > 0
            and order_count_window == 0
            and stalled
            and health_state in {"READY", "DEGRADED"}
        ):
            classification = "PIPELINE_STALL"
            detail["reason"] = "WAITING_OR_SELECTION_WITHOUT_ORDER_PROGRESS"
        elif order_count_window == 0 and not stack_components_down:
            if candidate_count_window == 0:
                classification = "NORMAL_NO_SIGNAL"
            else:
                classification = "PIPELINE_STALL" if waiting_count > 0 else "NORMAL_NO_SIGNAL"

    return {
        "classification": classification,
        "detail": detail,
        "evaluated_at": now.isoformat(),
    }
