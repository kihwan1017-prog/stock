"""Canonical why-no-trade terminal selection — lifecycle priority, not latest row."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from stock_platform.operation.upbit_entry_execution_trace.constants import (
    STAGE_ADMISSION_ACCEPTED,
    STAGE_ADMISSION_REJECTED,
    STAGE_BEGIN_ENTRY_ACCEPTED,
    STAGE_BEGIN_ENTRY_ATTEMPT,
    STAGE_BEGIN_ENTRY_REJECTED,
    STAGE_BROKER_ACCEPTED,
    STAGE_BROKER_REJECTED,
    STAGE_BROKER_SUBMITTED,
    STAGE_BUY_FILLED,
    STAGE_BUY_PARTIAL_FILL,
    STAGE_ENTRY_PASS,
    STAGE_ENTRY_PENDING_ROLLED_BACK,
    STAGE_EXECUTOR_RECEIVED,
    STAGE_EXECUTOR_REJECTED,
    STAGE_ORDER_INTENT_CREATED,
    STAGE_ORDER_PERSISTED,
    STAGE_OUTBOX_ENQUEUED,
    STAGE_SIGNAL_EMIT_ATTEMPT,
    STAGE_SIGNAL_EMITTED,
    STAGE_SIGNAL_SUPPRESSED,
)

# 낮을수록 terminal 우선순위 높음 — lifecycle 의미 순 (trade 완료 > reject > suppress > emit > telemetry)
_STAGE_TERMINAL_RANK: dict[str, int] = {
    STAGE_BUY_FILLED: 10,
    STAGE_BUY_PARTIAL_FILL: 15,
    STAGE_BROKER_ACCEPTED: 25,
    STAGE_BROKER_SUBMITTED: 30,
    STAGE_OUTBOX_ENQUEUED: 35,
    STAGE_ORDER_PERSISTED: 40,
    STAGE_ORDER_INTENT_CREATED: 45,
    STAGE_ADMISSION_ACCEPTED: 50,
    STAGE_BEGIN_ENTRY_ACCEPTED: 55,
    STAGE_EXECUTOR_RECEIVED: 60,
    STAGE_BROKER_REJECTED: 70,
    STAGE_BEGIN_ENTRY_REJECTED: 75,
    STAGE_ADMISSION_REJECTED: 80,
    STAGE_EXECUTOR_REJECTED: 85,
    STAGE_ENTRY_PENDING_ROLLED_BACK: 86,
    STAGE_SIGNAL_SUPPRESSED: 90,
    STAGE_SIGNAL_EMITTED: 100,
    STAGE_ENTRY_PASS: 110,
    STAGE_SIGNAL_EMIT_ATTEMPT: 120,
    STAGE_BEGIN_ENTRY_ATTEMPT: 130,
}


def _event_sort_key(event: dict[str, Any]) -> tuple[Any, ...]:
    """Deterministic ordering — created_at 동률 시 trace_row_id 사용."""
    created = event.get("created_at") or ""
    row_id = int(event.get("trace_row_id") or 0)
    return (created, row_id)


def _terminal_rank(event: dict[str, Any]) -> int:
    stage = str(event.get("stage") or "")
    rank = _STAGE_TERMINAL_RANK.get(stage, 999)
    # ENTRY_PASS REJECT(technical block)는 PASS telemetry보다 의미 있음
    if stage == STAGE_ENTRY_PASS and str(event.get("decision") or "").upper() == "REJECT":
        if event.get("reason_code"):
            return 105
        return 108
    return rank


def group_events_by_execution_trace(
    events: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        tid = str(event.get("execution_trace_id") or "")
        if tid:
            grouped[tid].append(event)
    for tid in grouped:
        grouped[tid].sort(key=_event_sort_key)
    return dict(grouped)


def resolve_current_execution_trace_id(
    events: list[dict[str, Any]],
) -> str | None:
    """가장 최근 activity가 있는 attempt — 영구 고정 아님."""
    if not events:
        return None
    latest = max(events, key=_event_sort_key)
    tid = latest.get("execution_trace_id")
    return str(tid) if tid else None


def select_canonical_terminal_event(
    attempt_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """단일 execution_trace_id attempt 내 lifecycle 우선 terminal."""
    if not attempt_events:
        return None
    return min(attempt_events, key=lambda e: (_terminal_rank(e), _event_sort_key(e)))


def select_terminal_for_events(
    events: list[dict[str, Any]],
    *,
    execution_trace_id: str | None = None,
) -> dict[str, Any] | None:
    """selection/symbol/trace 이벤트에서 canonical terminal row 선택."""
    if not events:
        return None
    if execution_trace_id:
        grouped = group_events_by_execution_trace(events)
        attempt = grouped.get(str(execution_trace_id), [])
        return select_canonical_terminal_event(attempt)
    tid = resolve_current_execution_trace_id(events)
    if not tid:
        return select_canonical_terminal_event(events)
    grouped = group_events_by_execution_trace(events)
    return select_canonical_terminal_event(grouped.get(tid, []))
