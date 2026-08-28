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
    UpbitLiveCandidateSelectionEntity,
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

# 시스템 장애 — consecutive block count 증가 금지
SYSTEM_SKIP_BLOCK_REASONS = frozenset(
    {
        "FEED_STALE",
        "FEED_UNAVAILABLE",
        "RUNTIME_DOWN",
        "RUNTIME_NOT_RUNNING",
        "EXIT_MONITOR_DOWN",
        "EXIT_MONITOR_NOT_RUNNING",
        "SYSTEM_UNAVAILABLE",
        "EVALUATION_SKIPPED",
        "STACK_NOT_READY",
    }
)


@dataclass(frozen=True, slots=True)
class WaitingSlotAssessment:
    slot_id: int
    symbol: str
    age_seconds: float
    waiting_started_at: datetime | None
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


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _aware(value)
    try:
        return _aware(
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return None


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


def _selection_selected_at(
    session: Session | None,
    slot: UpbitPositionSlotEntity,
) -> datetime | None:
    if session is None or slot.candidate_selection_id is None:
        return None
    sel = session.get(
        UpbitLiveCandidateSelectionEntity, int(slot.candidate_selection_id)
    )
    if sel is None:
        return None
    return _aware(getattr(sel, "selected_at", None))


def resolve_waiting_started_at(
    slot: UpbitPositionSlotEntity,
    *,
    session: Session | None = None,
    selection_selected_at: datetime | None = None,
    now: datetime | None = None,
) -> datetime:
    """WAITING age SoT — updated_at 사용 금지."""

    now = now or _now()
    meta = _slot_meta(slot)
    stored = _parse_iso(meta.get("waiting_started_at"))
    if stored is not None:
        return stored

    if selection_selected_at is not None:
        return _aware(selection_selected_at) or now

    sel_at = _selection_selected_at(session, slot)
    if sel_at is not None:
        return sel_at

    # backfill: created_at만 (updated_at은 revalidation마다 갱신됨)
    return _aware(slot.created_at) or now


def ensure_waiting_started_at(
    slot: UpbitPositionSlotEntity,
    *,
    session: Session | None = None,
    selection_selected_at: datetime | None = None,
) -> datetime:
    """기존 WAITING row backfill — waiting_started_at 없으면 provenance에서 1회 설정."""

    meta = _slot_meta(slot)
    if meta.get("waiting_started_at"):
        return _parse_iso(meta["waiting_started_at"]) or _now()
    started = resolve_waiting_started_at(
        slot,
        session=session,
        selection_selected_at=selection_selected_at,
    )
    meta["waiting_started_at"] = started.isoformat()
    _write_slot_meta(slot, meta)
    return started


def stamp_waiting_started_at(
    slot: UpbitPositionSlotEntity,
    *,
    started_at: datetime | None = None,
    reset: bool = False,
) -> None:
    """신규 WAITING 배정/교체 — waiting_started_at 설정 (교체 시 reset)."""

    meta = _slot_meta(slot)
    if not reset and meta.get("waiting_started_at"):
        return
    ts = _aware(started_at) or _now()
    meta["waiting_started_at"] = ts.isoformat()
    meta["consecutive_no_signal"] = 0
    meta.pop("last_revalidated_at", None)
    _write_slot_meta(slot, meta)


def waiting_age_seconds(
    slot: UpbitPositionSlotEntity,
    *,
    session: Session | None = None,
    now: datetime | None = None,
) -> float:
    """CURRENT_TIME - waiting_started_at."""

    now = now or _now()
    started = resolve_waiting_started_at(slot, session=session, now=now)
    return max(0.0, (now - started).total_seconds())


def oldest_waiting_age_seconds(
    session: Session,
    *,
    user_broker_account_id: int,
    now: datetime | None = None,
) -> float | None:
    """Watchdog starvation — metadata waiting_started_at 기준."""

    now = now or _now()
    slots = session.scalars(
        select(UpbitPositionSlotEntity).where(
            UpbitPositionSlotEntity.user_broker_account_id
            == int(user_broker_account_id),
            UpbitPositionSlotEntity.status == SLOT_WAITING_SIGNAL,
        )
    ).all()
    if not slots:
        return None
    ages = [
        waiting_age_seconds(s, session=session, now=now) for s in slots
    ]
    return max(ages) if ages else None


def _should_count_no_signal(telemetry: dict[str, Any]) -> bool:
    """fresh evaluation + entry 조건 실패만 count — 시스템 skip 제외."""

    if telemetry.get("evaluation_skipped"):
        return False
    reason = str(telemetry.get("last_block_reason") or "").upper()
    if reason in SYSTEM_SKIP_BLOCK_REASONS:
        return False
    if not telemetry.get("last_evaluated_at"):
        # 아직 entry evaluator 미실행 — count 증가 금지
        if not str(telemetry.get("last_decision") or "").strip():
            return False
    return True


def assess_waiting_slot(
    *,
    slot: UpbitPositionSlotEntity,
    policy: WaitingLifecyclePolicy,
    telemetry: dict[str, Any] | None,
    session: Session | None = None,
    now: datetime | None = None,
    count_block: bool = True,
) -> WaitingSlotAssessment:
    """Revalidation 판정 — BUY 생성 없음."""

    now = now or _now()
    sym = str(slot.symbol or "").upper()
    started = ensure_waiting_started_at(slot, session=session)
    age = max(0.0, (now - started).total_seconds())
    telem = telemetry or {}
    decision = str(telem.get("last_decision") or "").upper() or None
    if decision == "NONE":
        decision = None
    block_reason = str(telem.get("last_block_reason") or "") or None
    block_class = classify_waiting_block_reason(block_reason)

    meta = _slot_meta(slot)
    consecutive = int(meta.get("consecutive_no_signal") or 0)
    if count_block and _should_count_no_signal(telem):
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
        waiting_started_at=started,
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
    """slot metadata 갱신 — waiting_started_at 유지, updated_at만 heartbeat."""

    now = now or _now()
    meta = _slot_meta(slot)
    if not meta.get("waiting_started_at") and assessment.waiting_started_at:
        meta["waiting_started_at"] = assessment.waiting_started_at.isoformat()
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
    if assessment.last_decision in {"BUY", "TECHNICAL_PASS"}:
        meta["last_progress_at"] = now.isoformat()
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
            "waiting_started_at": (
                assessment.waiting_started_at.isoformat()
                if assessment.waiting_started_at
                else None
            ),
            "consecutive_no_signal": assessment.consecutive_no_signal,
            "block_reason": assessment.last_block_reason,
            "soft_stale": assessment.soft_stale,
            "release_eligible": assessment.release_eligible,
        },
    )


def force_waiting_revalidation_after_restore(
    session: Session,
    *,
    user_broker_account_id: int,
    actor: str = "restore_epoch",
) -> dict[str, Any]:
    """mark_restored 직후 WAITING 슬롯의 revalidation interval 을 해제한다.

    updated_at / last_revalidated_at 이 restored_at 이전이면
    STALE_PRE_RESTORE_WAITING 으로 BUY 가 영구 차단될 수 있다.
    REAL 주문은 생성하지 않고 meta 만 갱신한다.

    중요: mark_restored 와 같은 OS clock tick 에서 _now() 가 동일 시각을
    반환하면 updated_at == restored_at 이 되어 과거 <= 비교에서 고착됐다.
    restored_at 보다 엄격히 이후 updated_at 을 강제한다.
    """

    from datetime import timedelta

    from stock_platform.trading.upbit_execution_restore_epoch import (
        upbit_execution_restore_epoch,
    )

    uba_id = int(user_broker_account_id)
    slots = session.scalars(
        select(UpbitPositionSlotEntity).where(
            UpbitPositionSlotEntity.user_broker_account_id == uba_id,
            UpbitPositionSlotEntity.status == SLOT_WAITING_SIGNAL,
        )
    ).all()
    nudged = 0
    now = _now()
    # restore cutoff 엄격 이후 — equal timestamp STALE 고착 방지
    epoch = upbit_execution_restore_epoch.snapshot()
    restored = _parse_iso(epoch.get("restored_at"))
    if restored is not None and now <= restored:
        now = restored + timedelta(microseconds=1)
    for slot in slots:
        meta = _slot_meta(slot)
        meta["force_revalidate_after_restore"] = True
        meta["force_revalidate_at"] = now.isoformat()
        meta["force_revalidate_actor"] = str(actor or "")[:80]
        # interval 스킵 해제 — 다음 revalidate_waiting_slots 가 즉시 평가
        meta.pop("last_revalidated_at", None)
        _write_slot_meta(slot, meta)
        # restore cutoff 이후 updated_at 확보 — BUY gate 즉시 통과 가능
        slot.updated_at = now
        nudged += 1
    if nudged:
        session.flush()
    return {
        "ok": True,
        "uba_id": uba_id,
        "nudged_waiting_slots": nudged,
        "real_order_mutation": 0,
        "nudge_updated_at": now.isoformat(),
        "restore_cutoff": restored.isoformat() if restored else None,
    }


def release_waiting_slot_to_empty(
    session: Session,
    slot: UpbitPositionSlotEntity,
    *,
    reason: str,
    actor: str,
    assessment: WaitingSlotAssessment | None = None,
) -> dict[str, Any] | None:
    """WAITING → EMPTY — REAL order/binding 생성 금지."""

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
            prev = _parse_iso(last_rev)
            if prev is not None:
                elapsed = (_now() - prev).total_seconds()
                if elapsed < policy.revalidation_interval_seconds:
                    started = ensure_waiting_started_at(slot, session=session)
                    assessments.append(
                        {
                            "slot_id": int(slot.slot_id),
                            "symbol": sym,
                            "skipped": "REVALIDATION_INTERVAL",
                            "interval_remaining_seconds": round(
                                policy.revalidation_interval_seconds - elapsed, 1
                            ),
                            "waiting_started_at": started.isoformat(),
                            "age_seconds": round(
                                waiting_age_seconds(
                                    slot, session=session
                                ),
                                1,
                            ),
                        }
                    )
                    continue

        telem = telemetry_by_symbol.get(sym) or {}
        assessment = assess_waiting_slot(
            slot=slot,
            policy=policy,
            telemetry=telem,
            session=session,
        )
        record_waiting_revalidation(slot, assessment)
        assessments.append(
            {
                "slot_id": assessment.slot_id,
                "symbol": assessment.symbol,
                "waiting_started_at": (
                    assessment.waiting_started_at.isoformat()
                    if assessment.waiting_started_at
                    else None
                ),
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
