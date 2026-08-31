"""Append-only UPBIT entry execution trace — fail-open writes."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_entry_execution_trace.constants import (
    DECISION_ACCEPT,
    DECISION_FAIL,
    DECISION_PASS,
    DECISION_REJECT,
    DECISION_SKIP,
    INFRASTRUCTURE_FAILURE_REASONS,
    LIFECYCLE_INITIAL,
    LIFECYCLE_REVALIDATION,
    STAGE_ADMISSION_ACCEPTED,
    STAGE_ADMISSION_REJECTED,
    STAGE_BROKER_ACCEPTED,
    STAGE_BROKER_REJECTED,
    STAGE_BROKER_SUBMITTED,
    STAGE_BUY_FILLED,
    STAGE_BUY_PARTIAL_FILL,
    STAGE_EXECUTOR_RECEIVED,
    STAGE_EXECUTOR_REJECTED,
    STAGE_ORDER_PERSISTED,
    STAGE_OUTBOX_ENQUEUED,
    STAGE_SIGNAL_EMITTED,
    STAGE_SIGNAL_SUPPRESSED,
    TERMINAL_REJECT_STAGES,
    TRACE_COVERAGE_START_AT,
    utc_now,
)
from stock_platform.operation.upbit_entry_execution_trace.entities import (
    UpbitEntryExecutionTraceEntity,
)
from stock_platform.operation.upbit_entry_execution_trace.terminal_selection import (
    resolve_current_execution_trace_id,
    select_terminal_for_events,
)
from stock_platform.operation.upbit_entry_execution_trace.user_reasons import (
    friendly_reason,
    normalize_portfolio_reason,
)

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def new_execution_trace_id() -> str:
    return str(uuid.uuid4())


def _scrub(obj: Any) -> Any:
    banned = {"secret", "token", "password", "api_key", "credential"}
    if isinstance(obj, dict):
        return {
            k: _scrub(v)
            for k, v in obj.items()
            if not any(b in str(k).lower() for b in banned)
        }
    if isinstance(obj, list):
        return [_scrub(x) for x in obj]
    return obj


def build_idempotency_key(
    *,
    execution_trace_id: str,
    stage: str,
    decision: str,
    reason_code: str | None = None,
    related_object_id: str | None = None,
    lifecycle_kind: str | None = None,
) -> str:
    raw = "|".join(
        [
            execution_trace_id,
            stage,
            decision,
            str(reason_code or ""),
            str(related_object_id or ""),
            str(lifecycle_kind or ""),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def resolve_lifecycle_kind(
    session: Session,
    *,
    user_broker_account_id: int,
    selection_id: int | None,
) -> str:
    """동일 selection에 prior SIGNAL_EMITTED 있으면 REVALIDATION."""
    if selection_id is None:
        return LIFECYCLE_INITIAL
    try:
        prior = session.scalar(
            select(UpbitEntryExecutionTraceEntity.trace_row_id).where(
                UpbitEntryExecutionTraceEntity.user_broker_account_id
                == int(user_broker_account_id),
                UpbitEntryExecutionTraceEntity.selection_id == int(selection_id),
                UpbitEntryExecutionTraceEntity.stage == STAGE_SIGNAL_EMITTED,
            ).limit(1)
        )
        return LIFECYCLE_REVALIDATION if prior is not None else LIFECYCLE_INITIAL
    except Exception:  # noqa: BLE001
        return LIFECYCLE_INITIAL


def lookup_waiting_id(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    selection_id: int | None = None,
) -> int | None:
    """WAITING/ENTRY_PENDING slot_id — provenance only."""
    try:
        from stock_platform.operation.upbit_full_market.entities import (
            UpbitPositionSlotEntity,
        )

        q = select(UpbitPositionSlotEntity.slot_id).where(
            UpbitPositionSlotEntity.user_broker_account_id == int(user_broker_account_id),
            UpbitPositionSlotEntity.symbol == str(symbol).upper(),
        )
        if selection_id is not None:
            q = q.where(
                UpbitPositionSlotEntity.candidate_selection_id == int(selection_id)
            )
        sid = session.scalar(q.limit(1))
        return int(sid) if sid is not None else None
    except Exception:  # noqa: BLE001
        return None


def build_provenance(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    strategy_id: int | None,
    selection_id: int | None,
    execution_trace_id: str,
    lifecycle_kind: str,
    signal_id: str | None = None,
) -> dict[str, Any]:
    """StrategySignal.metadata / order.metadata_payload provenance."""
    waiting_id = lookup_waiting_id(
        session,
        user_broker_account_id=user_broker_account_id,
        symbol=symbol,
        selection_id=selection_id,
    )
    out: dict[str, Any] = {
        "execution_trace_id": execution_trace_id,
        "uba_id": int(user_broker_account_id),
        "lifecycle_kind": lifecycle_kind,
    }
    if selection_id is not None:
        out["selection_id"] = int(selection_id)
        out["candidate_selection_id"] = int(selection_id)
        out["candidate_id"] = int(selection_id)
    if waiting_id is not None:
        out["waiting_id"] = waiting_id
    if strategy_id is not None:
        out["strategy_id"] = int(strategy_id)
    if signal_id:
        out["signal_id"] = signal_id
    return out


def provenance_from_signal(signal: Any) -> dict[str, Any]:
    """RealtimeSignal provenance fields."""
    keys = (
        "execution_trace_id",
        "candidate_selection_id",
        "selection_id",
        "candidate_id",
        "waiting_id",
        "strategy_id",
        "signal_id",
        "lifecycle_kind",
        "uba_id",
    )
    out: dict[str, Any] = {}
    for k in keys:
        v = getattr(signal, k, None)
        if v is not None:
            out[k] = v
    return out


def append_stage(
    session: Session,
    *,
    execution_trace_id: str,
    user_broker_account_id: int,
    symbol: str,
    stage: str,
    decision: str,
    reason_code: str | None = None,
    reason_detail: str | None = None,
    selection_id: int | None = None,
    candidate_id: int | None = None,
    waiting_id: int | None = None,
    strategy_id: int | None = None,
    lifecycle_kind: str = LIFECYCLE_INITIAL,
    signal_id: str | None = None,
    order_id: int | None = None,
    outbox_id: int | None = None,
    related_object_id: str | None = None,
    detail: dict[str, Any] | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    sym = str(symbol or "").upper()
    idem = build_idempotency_key(
        execution_trace_id=execution_trace_id,
        stage=stage,
        decision=decision,
        reason_code=reason_code,
        related_object_id=related_object_id,
        lifecycle_kind=lifecycle_kind,
    )
    exists = session.scalar(
        select(UpbitEntryExecutionTraceEntity.trace_row_id).where(
            UpbitEntryExecutionTraceEntity.idempotency_key == idem
        )
    )
    if exists is not None:
        return {"ok": True, "duplicate": True, "idempotency_key": idem}
    row = UpbitEntryExecutionTraceEntity(
        execution_trace_id=str(execution_trace_id),
        user_broker_account_id=int(user_broker_account_id),
        selection_id=int(selection_id) if selection_id is not None else None,
        candidate_id=int(candidate_id) if candidate_id is not None else None,
        waiting_id=int(waiting_id) if waiting_id is not None else None,
        strategy_id=int(strategy_id) if strategy_id is not None else None,
        symbol=sym,
        lifecycle_kind=str(lifecycle_kind or LIFECYCLE_INITIAL),
        stage=stage,
        decision=decision,
        reason_code=str(reason_code)[:80] if reason_code else None,
        reason_detail=str(reason_detail)[:2000] if reason_detail else None,
        signal_id=str(signal_id)[:100] if signal_id else None,
        order_id=int(order_id) if order_id is not None else None,
        outbox_id=int(outbox_id) if outbox_id is not None else None,
        related_object_id=str(related_object_id)[:64] if related_object_id else None,
        idempotency_key=idem,
        detail_json=_scrub(detail or {}),
    )
    session.add(row)
    if commit:
        session.commit()
    else:
        session.flush()
    # Waiting lifecycle shadow — key REAL stages only (fail-open)
    try:
        stage_u = str(stage or "").upper()
        if stage_u in {
            "ENTRY_PASS",
            "SIGNAL_EMITTED",
            "ORDER_INTENT_CREATED",
            "ORDER_INTENT",
            "BUY_FILLED",
        } and str(decision or "").upper() in {"PASS", "ACCEPT", "BUY", ""}:
            # ENTRY_PASS REJECT는 technical block — evaluation 경로로만
            if stage_u != "ENTRY_PASS" or str(decision or "").upper() == "PASS":
                from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.hooks import (
                    on_real_entry_stage,
                )

                on_real_entry_stage(
                    session,
                    user_broker_account_id=int(user_broker_account_id),
                    symbol=sym,
                    selection_id=selection_id,
                    stage=stage_u,
                )
        reason_u = str(reason_code or "").upper()
        if reason_u in {
            "NO_WAITING_SIGNAL_SLOT",
            "FULL_MARKET_NO_WAITING_SIGNAL_SLOT",
            "PORTFOLIO_NO_WAITING_SIGNAL_SLOT",
        }:
            from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.hooks import (
                on_full_slot_or_no_waiting,
            )

            on_full_slot_or_no_waiting(
                session,
                user_broker_account_id=int(user_broker_account_id),
                symbol=sym,
                selection_id=selection_id,
                reason_code=reason_u,
            )
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "duplicate": False, "trace_row_id": int(row.trace_row_id)}


def append_stage_fail_open(session: Session, **kwargs: Any) -> dict[str, Any]:
    """REAL path — trace 실패가 trading을 막지 않음."""
    try:
        return append_stage(session, **kwargs)
    except Exception as exc:  # noqa: BLE001
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "upbit_entry_execution_trace_append_failed",
            extra={"error": type(exc).__name__, "stage": kwargs.get("stage")},
        )
        return {
            "ok": False,
            "code": "AUTOTRADING_TRACE_PERSIST_FAILED",
            "error": type(exc).__name__,
        }


def trace_id_from_metadata(meta: dict[str, Any] | None) -> str | None:
    if not isinstance(meta, dict):
        return None
    tid = meta.get("execution_trace_id")
    return str(tid) if tid else None


def get_trace_coverage_start_at(session: Session) -> datetime | None:
    global TRACE_COVERAGE_START_AT  # noqa: PLW0603
    if TRACE_COVERAGE_START_AT is not None:
        return TRACE_COVERAGE_START_AT
    try:
        row = session.execute(
            text(
                """
                SELECT MIN(created_at) FROM operation.upbit_entry_execution_trace
                """
            )
        ).scalar()
        if row is not None:
            TRACE_COVERAGE_START_AT = row
            return row
    except Exception:  # noqa: BLE001
        pass
    return None


def list_trace_events(
    session: Session,
    *,
    user_broker_account_id: int,
    selection_id: int | None = None,
    symbol: str | None = None,
    execution_trace_id: str | None = None,
    limit: int = 100,
    tail: bool = False,
) -> list[dict[str, Any]]:
    q = select(UpbitEntryExecutionTraceEntity).where(
        UpbitEntryExecutionTraceEntity.user_broker_account_id
        == int(user_broker_account_id)
    )
    if selection_id is not None:
        q = q.where(
            UpbitEntryExecutionTraceEntity.selection_id == int(selection_id)
        )
    if symbol:
        q = q.where(
            UpbitEntryExecutionTraceEntity.symbol == str(symbol).upper()
        )
    if execution_trace_id:
        q = q.where(
            UpbitEntryExecutionTraceEntity.execution_trace_id
            == str(execution_trace_id)
        )
    if tail:
        q = q.order_by(
            UpbitEntryExecutionTraceEntity.created_at.desc(),
            UpbitEntryExecutionTraceEntity.trace_row_id.desc(),
        ).limit(int(limit))
        rows = list(session.scalars(q))
        rows.reverse()
    else:
        q = q.order_by(
            UpbitEntryExecutionTraceEntity.created_at,
            UpbitEntryExecutionTraceEntity.trace_row_id,
        ).limit(int(limit))
        rows = list(session.scalars(q))
    return [_row_dict(r) for r in rows]


def _resolve_current_trace_id_from_db(
    session: Session,
    *,
    user_broker_account_id: int,
    selection_id: int | None = None,
    symbol: str | None = None,
) -> str | None:
    """DB에서 current attempt execution_trace_id — 전체 scan 없이 최신 attempt."""
    q = select(UpbitEntryExecutionTraceEntity.execution_trace_id).where(
        UpbitEntryExecutionTraceEntity.user_broker_account_id
        == int(user_broker_account_id)
    )
    if selection_id is not None:
        q = q.where(
            UpbitEntryExecutionTraceEntity.selection_id == int(selection_id)
        )
    if symbol:
        q = q.where(
            UpbitEntryExecutionTraceEntity.symbol == str(symbol).upper()
        )
    q = q.order_by(
        UpbitEntryExecutionTraceEntity.created_at.desc(),
        UpbitEntryExecutionTraceEntity.trace_row_id.desc(),
    ).limit(1)
    tid = session.scalar(q)
    return str(tid) if tid else None


def _load_attempt_events(
    session: Session,
    *,
    user_broker_account_id: int,
    execution_trace_id: str,
) -> list[dict[str, Any]]:
    return list_trace_events(
        session,
        user_broker_account_id=user_broker_account_id,
        execution_trace_id=execution_trace_id,
        limit=50,
    )


def _row_dict(r: UpbitEntryExecutionTraceEntity) -> dict[str, Any]:
    return {
        "trace_row_id": int(r.trace_row_id),
        "execution_trace_id": r.execution_trace_id,
        "uba_id": int(r.user_broker_account_id),
        "selection_id": r.selection_id,
        "candidate_id": r.candidate_id,
        "waiting_id": r.waiting_id,
        "strategy_id": r.strategy_id,
        "symbol": r.symbol,
        "lifecycle_kind": r.lifecycle_kind,
        "stage": r.stage,
        "decision": r.decision,
        "reason_code": r.reason_code,
        "reason_detail": r.reason_detail,
        "signal_id": r.signal_id,
        "order_id": r.order_id,
        "outbox_id": r.outbox_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "created_at_kst": (
            r.created_at.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")
            if r.created_at
            else None
        ),
        "user_friendly_reason": friendly_reason(r.reason_code),
        "detail": dict(r.detail_json or {}),
    }


def build_why_no_trade(
    session: Session,
    *,
    user_broker_account_id: int,
    selection_id: int | None = None,
    symbol: str | None = None,
    execution_trace_id: str | None = None,
) -> dict[str, Any]:
    """selection/symbol 기준 canonical why-no-trade — lifecycle priority terminal."""
    coverage_start = get_trace_coverage_start_at(session)
    current_trace_id = execution_trace_id
    if not current_trace_id:
        current_trace_id = _resolve_current_trace_id_from_db(
            session,
            user_broker_account_id=user_broker_account_id,
            selection_id=selection_id,
            symbol=symbol,
        )
    attempt_events: list[dict[str, Any]] = []
    if current_trace_id:
        attempt_events = _load_attempt_events(
            session,
            user_broker_account_id=user_broker_account_id,
            execution_trace_id=str(current_trace_id),
        )
    # UI timeline — 최근 attempt 주변 tail (first-N 버그 방지)
    events = list_trace_events(
        session,
        user_broker_account_id=user_broker_account_id,
        selection_id=selection_id,
        symbol=symbol,
        execution_trace_id=execution_trace_id,
        limit=100,
        tail=True,
    )
    if not attempt_events and not events:
        return {
            "ok": True,
            "provenance_status": "UNPROVEN",
            "historical_lineage_status": "UNPROVEN",
            "message": (
                "이 selection/symbol에 대한 영구 trace가 없습니다. "
                f"TRACE_COVERAGE_START_AT="
                f"{coverage_start.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S KST') if coverage_start else 'NOT_YET_DEPLOYED'}"
            ),
            "events": [],
            "terminal": False,
            "source": "ENTRY_EXECUTION_TRACE",
            "terminal_stage": None,
            "terminal_reason_code": None,
            "user_friendly_reason": None,
            "stage": None,
            "reason_code": None,
            "friendly_reason": None,
            "occurred_at": None,
        }
    terminal_source = attempt_events or events
    terminal = select_terminal_for_events(
        terminal_source,
        execution_trace_id=str(current_trace_id) if current_trace_id else None,
    )
    if terminal is None:
        terminal = select_terminal_for_events(events)
    resolved_trace_id = (
        str(current_trace_id)
        if current_trace_id
        else resolve_current_execution_trace_id(events)
    )
    def _scoped_exists(*filters: Any) -> bool:
        q = select(UpbitEntryExecutionTraceEntity.trace_row_id).where(
            UpbitEntryExecutionTraceEntity.user_broker_account_id
            == int(user_broker_account_id),
            *filters,
        )
        if selection_id is not None:
            q = q.where(
                UpbitEntryExecutionTraceEntity.selection_id == int(selection_id)
            )
        if symbol:
            q = q.where(
                UpbitEntryExecutionTraceEntity.symbol == str(symbol).upper()
            )
        return session.scalar(q.limit(1)) is not None

    has_order = _scoped_exists(UpbitEntryExecutionTraceEntity.order_id.is_not(None))
    has_fill = _scoped_exists(
        UpbitEntryExecutionTraceEntity.stage == STAGE_BUY_FILLED
    )
    proven = coverage_start is not None and (
        not events
        or not events[0].get("created_at")
        or events[0]["created_at"] >= coverage_start.isoformat()
    )
    reason_code = terminal.get("reason_code") if terminal else None
    friendly = (
        terminal.get("user_friendly_reason") if terminal else None
    ) or friendly_reason(reason_code)
    return {
        "ok": True,
        "provenance_status": "PROVEN" if proven else "UNPROVEN",
        "historical_lineage_status": "PROVEN" if proven else "UNPROVEN",
        "execution_trace_id": resolved_trace_id,
        "selection_id": selection_id or (events[0].get("selection_id") if events else None),
        "symbol": symbol or (events[0].get("symbol") if events else None),
        "events": events,
        "current_attempt_events": attempt_events,
        "terminal": True,
        "source": "ENTRY_EXECUTION_TRACE",
        "terminal_stage": terminal.get("stage") if terminal else None,
        "terminal_decision": terminal.get("decision") if terminal else None,
        "terminal_reason_code": reason_code,
        "user_friendly_reason": friendly,
        "stage": terminal.get("stage") if terminal else None,
        "reason_code": reason_code,
        "friendly_reason": friendly,
        "occurred_at": terminal.get("created_at_kst") if terminal else None,
        "order_created": has_order,
        "buy_filled": has_fill,
        "trace_coverage_start_at": (
            coverage_start.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")
            if coverage_start
            else None
        ),
    }


def is_policy_reject(reason_code: str | None) -> bool:
    if not reason_code:
        return False
    code = normalize_portfolio_reason(str(reason_code))
    if code in INFRASTRUCTURE_FAILURE_REASONS:
        return False
    return True


def detect_silent_gaps(
    session: Session,
    *,
    user_broker_account_id: int,
    window_minutes: int = 15,
) -> list[dict[str, Any]]:
    """SIGNAL_EMITTED 후 executor/begin/order terminal 없음 — watchdog용."""
    cutoff = utc_now() - timedelta(minutes=int(window_minutes))
    try:
        emitted = session.execute(
            text(
                """
                SELECT DISTINCT execution_trace_id, symbol, selection_id, created_at
                FROM operation.upbit_entry_execution_trace
                WHERE user_broker_account_id = :uba
                  AND stage = :stage
                  AND created_at >= :cutoff
                """
            ),
            {
                "uba": int(user_broker_account_id),
                "stage": STAGE_SIGNAL_EMITTED,
                "cutoff": cutoff,
            },
        ).mappings().all()
    except Exception:  # noqa: BLE001
        return []
    gaps: list[dict[str, Any]] = []
    for row in emitted:
        tid = str(row["execution_trace_id"])
        later = list_trace_events(
            session,
            user_broker_account_id=user_broker_account_id,
            execution_trace_id=tid,
            limit=50,
        )
        stages = {e["stage"] for e in later}
        terminal = stages & TERMINAL_REJECT_STAGES
        progressed = stages & {
            STAGE_EXECUTOR_RECEIVED,
            STAGE_BEGIN_ENTRY_ACCEPTED,
            STAGE_ORDER_PERSISTED,
            STAGE_BUY_FILLED,
        }
        if not terminal and not progressed:
            gaps.append(
                {
                    "execution_trace_id": tid,
                    "symbol": row["symbol"],
                    "selection_id": row["selection_id"],
                    "emitted_at": row["created_at"],
                    "gap_type": "SIGNAL_EMITTED_NO_FOLLOWUP",
                }
            )
        elif STAGE_BEGIN_ENTRY_ACCEPTED in stages and STAGE_ORDER_PERSISTED not in stages:
            if not (terminal & {STAGE_EXECUTOR_REJECTED, STAGE_ADMISSION_REJECTED}):
                gaps.append(
                    {
                        "execution_trace_id": tid,
                        "symbol": row["symbol"],
                        "selection_id": row["selection_id"],
                        "gap_type": "BEGIN_ENTRY_ACCEPTED_NO_ORDER",
                    }
                )
    return gaps
