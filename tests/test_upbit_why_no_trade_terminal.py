"""Canonical terminal selection — focused unit tests."""

from __future__ import annotations

from stock_platform.operation.upbit_entry_execution_trace.constants import (
    STAGE_BEGIN_ENTRY_REJECTED,
    STAGE_BROKER_ACCEPTED,
    STAGE_BUY_FILLED,
    STAGE_ENTRY_PASS,
    STAGE_EXECUTOR_REJECTED,
    STAGE_ORDER_PERSISTED,
    STAGE_SIGNAL_EMIT_ATTEMPT,
    STAGE_SIGNAL_EMITTED,
    STAGE_SIGNAL_SUPPRESSED,
)
from stock_platform.operation.upbit_entry_execution_trace.terminal_selection import (
    group_events_by_execution_trace,
    resolve_current_execution_trace_id,
    select_canonical_terminal_event,
    select_terminal_for_events,
)


def _ev(
    *,
    trace_row_id: int,
    execution_trace_id: str,
    stage: str,
    decision: str = "PASS",
    reason_code: str | None = None,
    created_at: str = "2026-08-28T02:00:00+00:00",
) -> dict:
    return {
        "trace_row_id": trace_row_id,
        "execution_trace_id": execution_trace_id,
        "stage": stage,
        "decision": decision,
        "reason_code": reason_code,
        "created_at": created_at,
    }


def test_suppressed_beats_repeated_entry_pass_same_attempt() -> None:
    """TEST 1 — ENTRY_PASS 후 SIGNAL_SUPPRESSED; telemetry가 terminal 덮지 않음."""
    tid = "trace-a"
    events = [
        _ev(trace_row_id=1, execution_trace_id=tid, stage=STAGE_ENTRY_PASS),
        _ev(
            trace_row_id=2,
            execution_trace_id=tid,
            stage=STAGE_SIGNAL_EMIT_ATTEMPT,
            created_at="2026-08-28T02:00:00+00:00",
        ),
        _ev(
            trace_row_id=3,
            execution_trace_id=tid,
            stage=STAGE_SIGNAL_SUPPRESSED,
            decision="SKIP",
            reason_code="SIGNAL_EMIT_SUPPRESSED",
            created_at="2026-08-28T02:00:00+00:00",
        ),
        _ev(
            trace_row_id=4,
            execution_trace_id=tid,
            stage=STAGE_ENTRY_PASS,
            created_at="2026-08-28T02:00:00+00:00",
        ),
    ]
    terminal = select_canonical_terminal_event(events)
    assert terminal is not None
    assert terminal["stage"] == STAGE_SIGNAL_SUPPRESSED
    assert terminal["reason_code"] == "SIGNAL_EMIT_SUPPRESSED"


def test_executor_rejected_beats_signal_emitted() -> None:
    """TEST 2 — SIGNAL_EMITTED → EXECUTOR_REJECTED."""
    tid = "trace-b"
    events = [
        _ev(trace_row_id=1, execution_trace_id=tid, stage=STAGE_SIGNAL_EMITTED),
        _ev(
            trace_row_id=2,
            execution_trace_id=tid,
            stage=STAGE_EXECUTOR_REJECTED,
            decision="REJECT",
            reason_code="PENDING_ENTRY_LIMIT",
        ),
    ]
    terminal = select_canonical_terminal_event(events)
    assert terminal["stage"] == STAGE_EXECUTOR_REJECTED


def test_begin_entry_rejected() -> None:
    """TEST 3 — BEGIN_ENTRY_REJECTED canonical."""
    tid = "trace-c"
    events = [
        _ev(trace_row_id=1, execution_trace_id=tid, stage=STAGE_SIGNAL_EMITTED),
        _ev(
            trace_row_id=2,
            execution_trace_id=tid,
            stage=STAGE_BEGIN_ENTRY_REJECTED,
            decision="REJECT",
            reason_code="NO_WAITING_SIGNAL_SLOT",
        ),
    ]
    terminal = select_canonical_terminal_event(events)
    assert terminal["stage"] == STAGE_BEGIN_ENTRY_REJECTED


def test_order_lifecycle_terminal() -> None:
    """TEST 4 — ORDER_PERSISTED / BROKER_ACCEPTED / BUY_FILLED."""
    tid = "trace-d"
    events = [
        _ev(trace_row_id=1, execution_trace_id=tid, stage=STAGE_SIGNAL_EMITTED),
        _ev(trace_row_id=2, execution_trace_id=tid, stage=STAGE_ORDER_PERSISTED),
        _ev(trace_row_id=3, execution_trace_id=tid, stage=STAGE_BROKER_ACCEPTED),
        _ev(trace_row_id=4, execution_trace_id=tid, stage=STAGE_BUY_FILLED),
    ]
    terminal = select_canonical_terminal_event(events)
    assert terminal["stage"] == STAGE_BUY_FILLED


def test_new_execution_attempt_uses_current_trace() -> None:
    """TEST 5 — 새 attempt가 current terminal 갱신."""
    old_tid = "trace-old"
    new_tid = "trace-new"
    events = [
        _ev(
            trace_row_id=1,
            execution_trace_id=old_tid,
            stage=STAGE_SIGNAL_SUPPRESSED,
            decision="SKIP",
            reason_code="SIGNAL_EMIT_SUPPRESSED",
            created_at="2026-08-28T02:00:00+00:00",
        ),
        _ev(
            trace_row_id=2,
            execution_trace_id=new_tid,
            stage=STAGE_ENTRY_PASS,
            decision="REJECT",
            reason_code="SHORT_MA_NOT_ABOVE_LONG_MA",
            created_at="2026-08-28T03:00:00+00:00",
        ),
    ]
    current = resolve_current_execution_trace_id(events)
    assert current == new_tid
    terminal = select_terminal_for_events(events)
    assert terminal is not None
    assert terminal["stage"] == STAGE_ENTRY_PASS
    assert terminal["reason_code"] == "SHORT_MA_NOT_ABOVE_LONG_MA"


def test_same_timestamp_deterministic_by_trace_row_id() -> None:
    """TEST 6 — 동일 timestamp에서 trace_row_id로 deterministic."""
    tid = "trace-ts"
    ts = "2026-08-28T02:22:04+00:00"
    events = [
        _ev(trace_row_id=10, execution_trace_id=tid, stage=STAGE_ENTRY_PASS, created_at=ts),
        _ev(
            trace_row_id=11,
            execution_trace_id=tid,
            stage=STAGE_SIGNAL_EMIT_ATTEMPT,
            created_at=ts,
        ),
        _ev(
            trace_row_id=12,
            execution_trace_id=tid,
            stage=STAGE_SIGNAL_SUPPRESSED,
            decision="SKIP",
            reason_code="SIGNAL_EMIT_SUPPRESSED",
            created_at=ts,
        ),
    ]
    terminal = select_canonical_terminal_event(events)
    assert terminal["stage"] == STAGE_SIGNAL_SUPPRESSED
    assert terminal["trace_row_id"] == 12


def test_explicit_execution_trace_id_scoped() -> None:
    """TEST 5b — explicit trace_id로 prior attempt terminal."""
    events = [
        _ev(
            trace_row_id=1,
            execution_trace_id="old",
            stage=STAGE_SIGNAL_SUPPRESSED,
            decision="SKIP",
            reason_code="SIGNAL_EMIT_SUPPRESSED",
        ),
        _ev(
            trace_row_id=2,
            execution_trace_id="new",
            stage=STAGE_ENTRY_PASS,
            decision="REJECT",
            reason_code="MA_SEPARATION_TOO_SMALL",
            created_at="2026-08-28T03:00:00+00:00",
        ),
    ]
    terminal = select_terminal_for_events(events, execution_trace_id="old")
    assert terminal["stage"] == STAGE_SIGNAL_SUPPRESSED


def test_group_by_execution_trace() -> None:
    grouped = group_events_by_execution_trace(
        [
            _ev(trace_row_id=1, execution_trace_id="a", stage=STAGE_ENTRY_PASS),
            _ev(trace_row_id=2, execution_trace_id="b", stage=STAGE_ENTRY_PASS),
        ]
    )
    assert set(grouped.keys()) == {"a", "b"}


def test_friendly_reason_mapping_for_suppress() -> None:
    """TEST 7 — SIGNAL_EMIT_SUPPRESSED friendly reason."""
    from stock_platform.operation.upbit_entry_execution_trace.user_reasons import (
        friendly_reason,
    )

    msg = friendly_reason("SIGNAL_EMIT_SUPPRESSED")
    assert msg is not None
    assert "진입 신호" in msg
