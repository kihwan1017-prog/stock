"""Order/outbox/broker fill trace from metadata provenance."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.operation.upbit_entry_execution_trace.constants import (
    DECISION_FAIL,
    DECISION_PASS,
    DECISION_REJECT,
    STAGE_ADMISSION_ACCEPTED,
    STAGE_ADMISSION_ATTEMPT,
    STAGE_ADMISSION_REJECTED,
    STAGE_BROKER_ACCEPTED,
    STAGE_BROKER_REJECTED,
    STAGE_BROKER_SUBMITTED,
    STAGE_BUY_FILLED,
    STAGE_BUY_PARTIAL_FILL,
)
from stock_platform.operation.upbit_entry_execution_trace.service import (
    append_stage_fail_open,
    trace_id_from_metadata,
)


def _base_from_metadata(meta: dict[str, Any], *, uba_id: int, symbol: str) -> dict[str, Any] | None:
    tid = trace_id_from_metadata(meta)
    if not tid:
        return None
    return {
        "execution_trace_id": tid,
        "user_broker_account_id": int(uba_id),
        "symbol": str(symbol).upper(),
        "selection_id": meta.get("candidate_selection_id") or meta.get("selection_id"),
        "candidate_id": meta.get("candidate_id"),
        "waiting_id": meta.get("waiting_id"),
        "strategy_id": meta.get("strategy_id"),
        "lifecycle_kind": meta.get("lifecycle_kind") or "INITIAL",
        "signal_id": meta.get("signal_id"),
    }


def trace_admission_attempt(
    session: Session,
    *,
    metadata: dict[str, Any] | None,
    uba_id: int,
    symbol: str,
) -> None:
    meta = metadata if isinstance(metadata, dict) else {}
    base = _base_from_metadata(meta, uba_id=uba_id, symbol=symbol)
    if not base:
        return
    append_stage_fail_open(
        session,
        **base,
        stage=STAGE_ADMISSION_ATTEMPT,
        decision=DECISION_PASS,
    )


def trace_admission_result(
    session: Session,
    *,
    metadata: dict[str, Any] | None,
    uba_id: int,
    symbol: str,
    allowed: bool,
    reason_code: str | None = None,
) -> None:
    meta = metadata if isinstance(metadata, dict) else {}
    base = _base_from_metadata(meta, uba_id=uba_id, symbol=symbol)
    if not base:
        return
    if allowed:
        append_stage_fail_open(
            session,
            **base,
            stage=STAGE_ADMISSION_ACCEPTED,
            decision=DECISION_PASS,
        )
        return
    append_stage_fail_open(
        session,
        **base,
        stage=STAGE_ADMISSION_REJECTED,
        decision=DECISION_REJECT,
        reason_code=str(reason_code or "ADMISSION_REJECTED"),
    )


def trace_order_broker_stage(
    session: Session,
    *,
    metadata: dict[str, Any] | None,
    uba_id: int | None,
    symbol: str,
    order_id: int,
    stage: str,
    decision: str = DECISION_PASS,
    reason_code: str | None = None,
    outbox_id: int | None = None,
    filled_qty: float | None = None,
) -> None:
    if uba_id is None:
        return
    meta = metadata if isinstance(metadata, dict) else {}
    base = _base_from_metadata(meta, uba_id=int(uba_id), symbol=symbol)
    if not base:
        return
    detail = {}
    if filled_qty is not None:
        detail["filled_quantity"] = filled_qty
    append_stage_fail_open(
        session,
        **base,
        stage=stage,
        decision=decision,
        reason_code=reason_code,
        order_id=int(order_id),
        outbox_id=outbox_id,
        detail=detail or None,
    )


def trace_broker_submit(session: Session, order: Any) -> None:
    meta = getattr(order, "metadata_payload", None) or {}
    trace_order_broker_stage(
        session,
        metadata=meta if isinstance(meta, dict) else {},
        uba_id=getattr(order, "user_broker_account_id", None),
        symbol=str(getattr(order, "symbol", "") or ""),
        order_id=int(order.order_id),
        stage=STAGE_BROKER_SUBMITTED,
    )


def trace_broker_accept(session: Session, order: Any) -> None:
    meta = getattr(order, "metadata_payload", None) or {}
    trace_order_broker_stage(
        session,
        metadata=meta if isinstance(meta, dict) else {},
        uba_id=getattr(order, "user_broker_account_id", None),
        symbol=str(getattr(order, "symbol", "") or ""),
        order_id=int(order.order_id),
        stage=STAGE_BROKER_ACCEPTED,
    )


def trace_buy_fill(session: Session, order: Any, *, partial: bool = False) -> None:
    meta = getattr(order, "metadata_payload", None) or {}
    stage = STAGE_BUY_PARTIAL_FILL if partial else STAGE_BUY_FILLED
    qty = float(getattr(order, "filled_quantity", 0) or 0)
    trace_order_broker_stage(
        session,
        metadata=meta if isinstance(meta, dict) else {},
        uba_id=getattr(order, "user_broker_account_id", None),
        symbol=str(getattr(order, "symbol", "") or ""),
        order_id=int(order.order_id),
        stage=stage,
        filled_qty=qty,
    )
