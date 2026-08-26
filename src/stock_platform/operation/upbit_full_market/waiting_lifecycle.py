"""UPBIT WAITING slot lifecycle — revalidation, soft stale, safe release (주문 생성 없음)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_full_market.constants import (
    SLOT_EMPTY,
    SLOT_WAITING_SIGNAL,
)
from stock_platform.operation.upbit_full_market.entities import (
    UpbitPortfolioPolicyEntity,
    UpbitPositionSlotEntity,
)
from stock_platform.operation.upbit_full_market.waiting_lifecycle_policy import (
    REASON_CONSECUTIVE_BLOCK_RELEASE,
    REASON_HARD_EXPIRE_NO_SIGNAL,
    WaitingLifecyclePolicy,
    classify_waiting_block_reason,
    load_waiting_lifecycle_policy,
)

logger = logging.getLogger(__name__)

META_KEY = "waiting_lifecycle_v1"

# audit event types (telemetry / log)
EVT_REVALIDATED = "WAITING_REVALIDATED"
EVT_BLOCKED = "WAITING_BLOCKED"
EVT_SOFT_STALE = "WAITING_SOFT_STALE"
EVT_RELEASED = "WAITING_RELEASED"
EVT_REPLACED = "WAITING_REPLACED"


@dataclass(frozen=True, slots=True)
class WaitingSlotAssessment:
    slot_id: int
    symbol: str
    age_seconds: float
    consecutive_no_signal: int
    last_decision: str | None
    last_block_reason: str | None
    block_class: str
    soft_stale: bool
    hard_expired: bool
    release_eligible: bool
    release_reason: str | None
    replacement_eligible: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _slot_meta(slot: UpbitPositionSlotEntity) -> dict[str, Any]:
    raw = slot.clamp_reasons
    if isinstance(raw, dict):
        meta = raw.get(META_KEY)
        return dict(meta) if isinstance(meta, dict) else {}
    return {}


def _write_slot_meta(slot: UpbitPositionSlotEntity, meta: dict[str, Any]) -> None:
    raw = slot.clamp_reasons
    if isinstance(raw, dict):
        base = dict(raw)
    elif isinstance(raw, list):
        base = {"capital_clamps": list(raw)}
    else:
        base = {}
    base[META_KEY] = meta
    slot.clamp_reasons = base


def _is_no_entry_progress(decision: str | None) -> bool:
    d = str(decision or "").upper()
    return d not in {"BUY", "TECHNICAL_PASS"}


def assess_waiting_slot(
    *,
    slot: UpbitPositionSlotEntity,
    policy: WaitingLifecyclePolicy,
    telemetry: dict[str, Any] | None,
    now: datetime | None = None,
) -> WaitingSlotAssessment:
    """Revalidation 판정 — BUY 생성 없음."""

    now = now or _now()
    sym = str(slot.symbol or "").upper()
    anchor = _aware(slot.updated_at) or _aware(slot.created_at) or now
    age = max(0.0, (now - anchor).total_seconds())
    telem = telemetry or {}
    decision = str(telem.get("last_decision") or "").upper() or None
    block_reason = str(telem.get("last_block_reason") or "") or None
    block_class = classify_waiting_block_reason(block_reason)

    meta = _slot_meta(slot)
    consecutive = int(meta.get("consecutive_no_signal") or 0)
    if _is_no_entry_progress(decision):
        consecutive += 1
    else:
        consecutive = 0

    soft_stale = (
        age >= policy.soft_stale_seconds
        and _is_no_entry_progress(decision)
        and consecutive >= policy.consecutive_no_signal_threshold
    )
    hard_expired = (
        age >= policy.hard_expire_no_signal_seconds
        and _is_no_entry_progress(decision)
        and consecutive >= policy.consecutive_no_signal_threshold
    )

    release_reason: str | None = None
    release_eligible = False
    if hard_expired:
        release_eligible = True
        release_reason = REASON_HARD_EXPIRE_NO_SIGNAL
    elif (
        age >= policy.hard_expire_no_signal_seconds
        and block_class == "TERMINAL"
        and consecutive >= policy.consecutive_no_signal_threshold
    ):
        release_eligible = True
        release_reason = REASON_CONSECUTIVE_BLOCK_RELEASE
    elif (
        consecutive >= policy.consecutive_no_signal_threshold + 2
        and age >= policy.soft_stale_seconds
        and _is_no_entry_progress(decision)
    ):
        release_eligible = True
        release_reason = REASON_CONSECUTIVE_BLOCK_RELEASE

    replacement_eligible = (
        soft_stale
        and age >= policy.hold_seconds
        and _is_no_entry_progress(decision)
    )

    return WaitingSlotAssessment(
        slot_id=int(slot.slot_id),
        symbol=sym,
        age_seconds=age,
        consecutive_no_signal=consecutive,
        last_decision=decision,
        last_block_reason=block_reason,
        block_class=block_class,
        soft_stale=soft_stale,
        hard_expired=hard_expired,
        release_eligible=release_eligible,
        release_reason=release_reason,
        replacement_eligible=replacement_eligible,
    )


def record_waiting_revalidation(
    slot: UpbitPositionSlotEntity,
    assessment: WaitingSlotAssessment,
    *,
    now: datetime | None = None,
) -> None:
    """slot metadata 갱신 — debounce counter."""

    now = now or _now()
    meta = _slot_meta(slot)
    meta.update(
        {
            "consecutive_no_signal": assessment.consecutive_no_signal,
            "last_revalidated_at": now.isoformat(),
            "last_decision": assessment.last_decision,
            "last_block_reason": assessment.last_block_reason,
            "soft_stale": assessment.soft_stale,
            "hard_expired": assessment.hard_expired,
        }
    )
    _write_slot_meta(slot, meta)
    slot.updated_at = now

    event = EVT_SOFT_STALE if assessment.soft_stale else EVT_REVALIDATED
    if assessment.last_decision == "BLOCK" or assessment.last_block_reason:
        event = EVT_BLOCKED
    logger.info(
        "upbit_waiting_lifecycle_event",
        extra={
            "event": event,
            "slot_id": assessment.slot_id,
            "symbol": assessment.symbol,
            "age_seconds": round(assessment.age_seconds, 1),
            "consecutive_no_signal": assessment.consecutive_no_signal,
            "block_reason": assessment.last_block_reason,
            "soft_stale": assessment.soft_stale,
            "release_eligible": assessment.release_eligible,
        },
    )


def release_waiting_slot_to_empty(
    session: Session,
    slot: UpbitPositionSlotEntity,
    *,
    reason: str,
    actor: str,
    assessment: WaitingSlotAssessment | None = None,
) -> dict[str, Any] | None:
    """WAITING → EMPTY — REAL order/binding 생성 금지."""

    # OPEN binding / 진행 중 entry order 있으면 release 금지
    if slot.entry_order_id is not None:
        return None
    if slot.position_binding_id is not None:
        return None

    prior = str(slot.status)
    sym = str(slot.symbol or "").upper()
    now = _now()
    slot.status = SLOT_EMPTY
    slot.symbol = None
    slot.candidate_selection_id = None
    slot.scanner_run_id = None
    slot.ai_analysis_id = None
    slot.entry_order_id = None
    slot.position_binding_id = None
    slot.reserved_amount_krw = None
    slot.allocated_amount_krw = None
    slot.opened_at = None
    slot.closed_at = None
    slot.cooldown_until = None
    slot.version = int(slot.version or 1) + 1
    slot.updated_at = now
    meta = _slot_meta(slot)
    meta["released_at"] = now.isoformat()
    meta["release_reason"] = reason
    meta["released_by"] = actor
    _write_slot_meta(slot, meta)

    logger.info(
        "upbit_waiting_lifecycle_event",
        extra={
            "event": EVT_RELEASED,
            "slot_id": int(slot.slot_id),
            "symbol": sym,
            "reason": reason,
            "actor": actor,
            "age_seconds": (
                round(assessment.age_seconds, 1) if assessment else None
            ),
        },
    )
    return {
        "slot_id": int(slot.slot_id),
        "symbol": sym,
        "from": prior,
        "to": SLOT_EMPTY,
        "changes": [reason],
        "release_reason": reason,
        "actor": actor,
        "waiting_age_seconds": assessment.age_seconds if assessment else None,
    }


def revalidate_waiting_slots(
    session: Session,
    *,
    user_broker_account_id: int,
    telemetry_by_symbol: dict[str, dict[str, Any]],
    actor: str = "waiting_lifecycle",
    policy: WaitingLifecyclePolicy | None = None,
) -> dict[str, Any]:
    """주기 revalidation — release만 (replacement는 consume_top_k)."""

    from stock_platform.common.settings import get_settings

    uba_id = int(user_broker_account_id)
    if policy is None:
        pol_row = session.scalar(
            select(UpbitPortfolioPolicyEntity).where(
                UpbitPortfolioPolicyEntity.user_broker_account_id == uba_id
            )
        )
        rg = dict(getattr(pol_row, "risk_group_policy_json", None) or {})
        policy = load_waiting_lifecycle_policy(
            settings=get_settings(),
            risk_group_policy_json=rg,
        )

    slots = session.scalars(
        select(UpbitPositionSlotEntity)
        .where(
            UpbitPositionSlotEntity.user_broker_account_id == uba_id,
            UpbitPositionSlotEntity.status == SLOT_WAITING_SIGNAL,
        )
        .order_by(UpbitPositionSlotEntity.slot_no)
    ).all()

    transitions: list[dict[str, Any]] = []
    assessments: list[dict[str, Any]] = []
    released = 0
    soft_stale_n = 0

    for slot in slots:
        sym = str(slot.symbol or "").upper()
        meta = _slot_meta(slot)
        last_rev = meta.get("last_revalidated_at")
        if last_rev:
            try:
                prev = datetime.fromisoformat(str(last_rev).replace("Z", "+00:00"))
                if prev.tzinfo is None:
                    prev = prev.replace(tzinfo=timezone.utc)
                elapsed = (_now() - prev.astimezone(timezone.utc)).total_seconds()
                if elapsed < policy.revalidation_interval_seconds:
                    assessments.append(
                        {
                            "slot_id": int(slot.slot_id),
                            "symbol": sym,
                            "skipped": "REVALIDATION_INTERVAL",
                            "interval_remaining_seconds": round(
                                policy.revalidation_interval_seconds - elapsed, 1
                            ),
                        }
                    )
                    continue
            except (TypeError, ValueError):
                pass

        telem = telemetry_by_symbol.get(sym) or {}
        assessment = assess_waiting_slot(
            slot=slot, policy=policy, telemetry=telem
        )
        record_waiting_revalidation(slot, assessment)
        assessments.append(
            {
                "slot_id": assessment.slot_id,
                "symbol": assessment.symbol,
                "age_seconds": round(assessment.age_seconds, 1),
                "consecutive_no_signal": assessment.consecutive_no_signal,
                "last_decision": assessment.last_decision,
                "last_block_reason": assessment.last_block_reason,
                "soft_stale": assessment.soft_stale,
                "release_eligible": assessment.release_eligible,
                "replacement_eligible": assessment.replacement_eligible,
            }
        )
        if assessment.soft_stale:
            soft_stale_n += 1
        if assessment.release_eligible and assessment.release_reason:
            tr = release_waiting_slot_to_empty(
                session,
                slot,
                reason=assessment.release_reason,
                actor=actor,
                assessment=assessment,
            )
            if tr is None:
                continue
            transitions.append(tr)
            released += 1

    if transitions:
        session.flush()

    return {
        "ok": True,
        "uba_id": uba_id,
        "revalidated": len(slots),
        "released": released,
        "soft_stale_count": soft_stale_n,
        "transitions": transitions,
        "assessments": assessments,
        "policy": {
            "soft_stale_seconds": policy.soft_stale_seconds,
            "hard_expire_no_signal_seconds": policy.hard_expire_no_signal_seconds,
            "consecutive_no_signal_threshold": policy.consecutive_no_signal_threshold,
        },
    }


def detect_waiting_slot_starvation(
    *,
    waiting_count: int,
    empty_count: int,
    max_positions: int,
    quota_remaining: int,
    stack_ready: bool,
    oldest_waiting_age_seconds: float | None,
    order_count_window: int,
    candidate_or_selection_active: bool,
    policy: WaitingLifecyclePolicy,
) -> dict[str, Any]:
    """Watchdog / health — starvation 판정."""

    full = waiting_count >= max_positions and empty_count == 0
    starvation = (
        full
        and quota_remaining > 0
        and stack_ready
        and candidate_or_selection_active
        and order_count_window == 0
        and oldest_waiting_age_seconds is not None
        and oldest_waiting_age_seconds
        >= policy.starvation_degraded_seconds
    )
    escalation = "NONE"
    if starvation and oldest_waiting_age_seconds is not None:
        if oldest_waiting_age_seconds >= policy.starvation_broken_seconds:
            escalation = "BROKEN"
        else:
            escalation = "DEGRADED"
    return {
        "waiting_slot_starvation": starvation,
        "escalation": escalation,
        "oldest_waiting_age_seconds": oldest_waiting_age_seconds,
    }
