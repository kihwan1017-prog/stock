"""MaEvaluator / executor / begin_entry hooks — fail-open entry execution trace."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.operation.upbit_entry_execution_trace.constants import (
    DECISION_ACCEPT,
    DECISION_PASS,
    DECISION_REJECT,
    DECISION_SKIP,
    LIFECYCLE_INITIAL,
    STAGE_BEGIN_ENTRY_ACCEPTED,
    STAGE_BEGIN_ENTRY_ATTEMPT,
    STAGE_BEGIN_ENTRY_REJECTED,
    STAGE_ENTRY_PASS,
    STAGE_SIGNAL_EMIT_ATTEMPT,
    STAGE_SIGNAL_EMITTED,
    STAGE_SIGNAL_SUPPRESSED,
)
from stock_platform.operation.upbit_entry_execution_trace.context import get_current
from stock_platform.operation.upbit_entry_execution_trace.service import (
    append_stage_fail_open,
    build_provenance,
    new_execution_trace_id,
    resolve_lifecycle_kind,
)


def trace_bullish_evaluation(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    strategy_id: int | None,
    selection_id: int | None,
    technical_ok: bool,
    block_reason: str | None,
    signal_emitted: bool,
    signal_id: str | None = None,
    detail: dict[str, Any] | None = None,
    execution_trace_id: str | None = None,
) -> dict[str, Any]:
    """MaEvaluator BULLISH path — ENTRY_PASS / emit / suppress."""
    sym = str(symbol).upper()
    lifecycle = resolve_lifecycle_kind(
        session,
        user_broker_account_id=user_broker_account_id,
        selection_id=selection_id,
    )
    trace_id = execution_trace_id or new_execution_trace_id()
    prov = build_provenance(
        session,
        user_broker_account_id=user_broker_account_id,
        symbol=sym,
        strategy_id=strategy_id,
        selection_id=selection_id,
        execution_trace_id=trace_id,
        lifecycle_kind=lifecycle,
        signal_id=signal_id,
    )
    base = {
        "execution_trace_id": trace_id,
        "user_broker_account_id": int(user_broker_account_id),
        "symbol": sym,
        "selection_id": selection_id,
        "candidate_id": selection_id,
        "waiting_id": prov.get("waiting_id"),
        "strategy_id": strategy_id,
        "lifecycle_kind": lifecycle,
        "signal_id": signal_id,
        "detail": {"provenance": prov, **(detail or {})},
    }
    if not technical_ok:
        append_stage_fail_open(
            session,
            **base,
            stage=STAGE_ENTRY_PASS,
            decision=DECISION_REJECT,
            reason_code=block_reason,
        )
        return {"execution_trace_id": trace_id, "provenance": prov}
    append_stage_fail_open(
        session,
        **base,
        stage=STAGE_ENTRY_PASS,
        decision=DECISION_PASS,
    )
    append_stage_fail_open(
        session,
        **base,
        stage=STAGE_SIGNAL_EMIT_ATTEMPT,
        decision=DECISION_PASS,
    )
    if signal_emitted:
        append_stage_fail_open(
            session,
            **base,
            stage=STAGE_SIGNAL_EMITTED,
            decision=DECISION_PASS,
            signal_id=signal_id,
        )
    else:
        append_stage_fail_open(
            session,
            **base,
            stage=STAGE_SIGNAL_SUPPRESSED,
            decision=DECISION_SKIP,
            reason_code="SIGNAL_EMIT_SUPPRESSED",
        )
    return {"execution_trace_id": trace_id, "provenance": prov}


def trace_begin_entry_attempt(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
) -> None:
    _trace_begin_stage(
        session,
        user_broker_account_id=user_broker_account_id,
        symbol=symbol,
        stage=STAGE_BEGIN_ENTRY_ATTEMPT,
        decision=DECISION_PASS,
    )


def trace_begin_entry_result(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    result: dict[str, Any],
    waiting_id: int | None = None,
    selection_id: int | None = None,
) -> None:
    if result.get("ok") or result.get("already"):
        _trace_begin_stage(
            session,
            user_broker_account_id=user_broker_account_id,
            symbol=symbol,
            stage=STAGE_BEGIN_ENTRY_ACCEPTED,
            decision=DECISION_ACCEPT,
            waiting_id=waiting_id or result.get("slot_id"),
            selection_id=selection_id,
        )
        return
    _trace_begin_stage(
        session,
        user_broker_account_id=user_broker_account_id,
        symbol=symbol,
        stage=STAGE_BEGIN_ENTRY_REJECTED,
        decision=DECISION_REJECT,
        reason_code=str(result.get("reason") or "BEGIN_ENTRY_FAILED"),
        waiting_id=waiting_id,
        selection_id=selection_id,
        detail={"result": _scrub_result(result)},
    )


def _scrub_result(result: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in result.items() if k not in {"allocation", "sizing"}}


def _trace_begin_stage(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    stage: str,
    decision: str,
    reason_code: str | None = None,
    waiting_id: int | None = None,
    selection_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    ctx = get_current() or {}
    trace_id = ctx.get("execution_trace_id")
    if not trace_id:
        return
    append_stage_fail_open(
        session,
        execution_trace_id=str(trace_id),
        user_broker_account_id=int(user_broker_account_id),
        symbol=str(symbol).upper(),
        stage=stage,
        decision=decision,
        reason_code=reason_code,
        selection_id=selection_id or ctx.get("candidate_selection_id"),
        candidate_id=selection_id or ctx.get("candidate_id"),
        waiting_id=waiting_id or ctx.get("waiting_id"),
        strategy_id=ctx.get("strategy_id"),
        lifecycle_kind=str(ctx.get("lifecycle_kind") or LIFECYCLE_INITIAL),
        signal_id=ctx.get("signal_id"),
        detail=detail,
    )
