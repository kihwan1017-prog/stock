"""Waiting Lifecycle Forward Shadow Lab — research simulation (fail-open toward REAL)."""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.epoch import (
    get_or_create_feature_epoch,
)
from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.constants import (
    ALL_VARIANTS,
    COHORT_PREEXISTING,
    COHORT_PRIMARY_FORWARD,
    EARLY_REVIEW_N,
    EVENT_DEDUPE_SECONDS,
    EVT_ABSOLUTE_EXPIRED,
    EVT_BUY_FILLED,
    EVT_COUNTERFACTUAL_UNOBSERVABLE,
    EVT_ENROLLED,
    EVT_ENTRY_PASS,
    EVT_EVALUATED,
    EVT_FULL_SLOT_BLOCK,
    EVT_ORDER_INTENT,
    EVT_REAL_LATER_BOUGHT,
    EVT_REPLACED,
    EVT_REPLACEMENT_ELIGIBLE,
    EVT_SHADOW_ADMITTED,
    EVT_SIGNAL_EMITTED,
    EVT_STALE,
    EVT_TECHNICAL_BLOCK,
    EVT_TECHNICAL_PASS,
    EVT_WOULD_ADMIT,
    EVT_WOULD_BLOCK,
    EVT_WOULD_EXPIRE_EXISTING,
    EVT_WOULD_REPLACE,
    FEATURE_DEPLOY_EPOCH,
    FEATURE_DEPLOY_EPOCH_SOURCE,
    FEATURE_KEY,
    LAB_ID,
    RULE_VERSION,
    SHADOW_CAPACITY,
    SHADOW_SIM_VARIANTS,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_REPLACED,
    STATUS_STALE,
    STATUS_SUCCESS_TERMINAL,
    STRONG_REVIEW_N,
    TERMINAL_STATUSES,
    VARIANT_R0,
    VARIANT_R3,
)
from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.entities import (
    UpbitWaitingLifecycleShadowEventEntity,
    UpbitWaitingLifecycleShadowObservationEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.policy import (
    policy_for,
)

logger = structlog.get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def shadow_enabled(settings: Any | None = None) -> bool:
    settings = settings or get_settings()
    return bool(
        getattr(settings, "upbit_waiting_lifecycle_shadow_enabled", True)
    )


def deployment_epoch(session: Session) -> datetime:
    epoch, _src = get_or_create_feature_epoch(
        session,
        feature_key=FEATURE_KEY,
        seed_epoch=FEATURE_DEPLOY_EPOCH,
        seed_source=FEATURE_DEPLOY_EPOCH_SOURCE,
    )
    return _aware(epoch) or FEATURE_DEPLOY_EPOCH


def shadow_age_seconds(
    row: UpbitWaitingLifecycleShadowObservationEntity,
    *,
    now: datetime | None = None,
) -> float:
    """Monotonic age from ttl_anchor — TECHNICAL_PASS로 reset 금지."""

    now = _aware(now) or _now()
    anchor = _aware(row.ttl_anchor_at) or _aware(row.enrolled_at) or now
    return max(0.0, (now - anchor).total_seconds())


def _append_event(
    session: Session,
    *,
    observation_id: int | None,
    uba_id: int,
    variant: str,
    event_type: str,
    observed_at: datetime | None = None,
    age_seconds: float | None = None,
    decision: str | None = None,
    block_reason: str | None = None,
    score: float | None = None,
    symbol: str | None = None,
    selection_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    force: bool = False,
) -> bool:
    """Coalesce duplicate noisy events (fail-open caller)."""

    now = _aware(observed_at) or _now()
    dedupe = "|".join(
        [
            str(observation_id or 0),
            str(variant),
            str(event_type),
            str(decision or ""),
            str(block_reason or ""),
            str(selection_id or ""),
        ]
    )[:200]
    if not force and event_type in {
        EVT_EVALUATED,
        EVT_TECHNICAL_BLOCK,
        EVT_TECHNICAL_PASS,
        EVT_FULL_SLOT_BLOCK,
        EVT_WOULD_BLOCK,
    }:
        cutoff = now - timedelta(seconds=EVENT_DEDUPE_SECONDS)
        exists = session.scalar(
            select(UpbitWaitingLifecycleShadowEventEntity.event_id).where(
                UpbitWaitingLifecycleShadowEventEntity.dedupe_key == dedupe,
                UpbitWaitingLifecycleShadowEventEntity.observed_at >= cutoff,
            )
        )
        if exists is not None:
            return False
    session.add(
        UpbitWaitingLifecycleShadowEventEntity(
            observation_id=observation_id,
            user_broker_account_id=int(uba_id),
            variant=str(variant),
            event_type=str(event_type),
            observed_at=now,
            age_seconds=age_seconds,
            decision=decision,
            block_reason=block_reason,
            score=score,
            symbol=symbol,
            selection_id=selection_id,
            dedupe_key=dedupe,
            metadata_json=dict(metadata or {}),
        )
    )
    return True


def _active_count(
    session: Session, *, uba_id: int, variant: str
) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(UpbitWaitingLifecycleShadowObservationEntity)
            .where(
                UpbitWaitingLifecycleShadowObservationEntity.user_broker_account_id
                == int(uba_id),
                UpbitWaitingLifecycleShadowObservationEntity.variant == variant,
                UpbitWaitingLifecycleShadowObservationEntity.status.in_(
                    [STATUS_ACTIVE, STATUS_STALE]
                ),
            )
        )
        or 0
    )


def _find_active(
    session: Session,
    *,
    uba_id: int,
    variant: str,
    selection_id: int,
) -> UpbitWaitingLifecycleShadowObservationEntity | None:
    return session.scalar(
        select(UpbitWaitingLifecycleShadowObservationEntity).where(
            UpbitWaitingLifecycleShadowObservationEntity.user_broker_account_id
            == int(uba_id),
            UpbitWaitingLifecycleShadowObservationEntity.variant == variant,
            UpbitWaitingLifecycleShadowObservationEntity.selection_id
            == int(selection_id),
            UpbitWaitingLifecycleShadowObservationEntity.status.in_(
                [STATUS_ACTIVE, STATUS_STALE]
            ),
        )
    )


def enroll_waiting_opportunity(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    selection_id: int,
    waiting_created_at: datetime,
    candidate_id: int | None = None,
    candidate_snapshot_id: str | None = None,
    strategy_id: int | None = None,
    deployment_id: int | None = None,
    slot_id: int | None = None,
    initial_score: float | None = None,
    cohort: str | None = None,
    variants: tuple[str, ...] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """REAL WAITING 배정 관측 → variant별 독립 enroll (REAL release 없음)."""

    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    now = _aware(now) or _now()
    uba_id = int(user_broker_account_id)
    sym = str(symbol or "").upper()
    sel_id = int(selection_id)
    created = _aware(waiting_created_at) or now
    epoch = deployment_epoch(session)
    # PRIMARY: activation 이후 신규 waiting만. preexisting는 별도 cohort.
    if cohort is None:
        if created < epoch:
            cohort = COHORT_PREEXISTING
        else:
            cohort = COHORT_PRIMARY_FORWARD
    # preexisting TTL은 enrolled_at부터 (즉시 expired 금지)
    if cohort == COHORT_PREEXISTING:
        ttl_anchor = now
    else:
        ttl_anchor = created

    results: dict[str, Any] = {"ok": True, "lab_id": LAB_ID, "variants": {}}
    for variant in variants or ALL_VARIANTS:
        existing = session.scalar(
            select(UpbitWaitingLifecycleShadowObservationEntity).where(
                UpbitWaitingLifecycleShadowObservationEntity.user_broker_account_id
                == uba_id,
                UpbitWaitingLifecycleShadowObservationEntity.variant == variant,
                UpbitWaitingLifecycleShadowObservationEntity.selection_id
                == sel_id,
                UpbitWaitingLifecycleShadowObservationEntity.cohort == cohort,
            )
        )
        if existing is not None:
            results["variants"][variant] = {
                "ok": True,
                "reason": "ALREADY_ENROLLED",
                "observation_id": int(existing.observation_id),
            }
            continue

        # R1/R2/R3 capacity — R0은 REAL waiting 전수 관측 (capacity 제한 없음,
        # 단 ACTIVE 상한은 SHADOW_CAPACITY로 맞춤 보고용)
        active_n = _active_count(session, uba_id=uba_id, variant=variant)
        if variant in SHADOW_SIM_VARIANTS and active_n >= SHADOW_CAPACITY:
            _append_event(
                session,
                observation_id=None,
                uba_id=uba_id,
                variant=variant,
                event_type=EVT_FULL_SLOT_BLOCK,
                observed_at=now,
                symbol=sym,
                selection_id=sel_id,
                score=initial_score,
                metadata={"active_n": active_n, "capacity": SHADOW_CAPACITY},
            )
            # R3 replacement attempt
            if variant == VARIANT_R3:
                repl = _try_shadow_replace(
                    session,
                    uba_id=uba_id,
                    new_symbol=sym,
                    new_selection_id=sel_id,
                    new_score=initial_score,
                    now=now,
                    waiting_created_at=created,
                    candidate_id=candidate_id,
                    strategy_id=strategy_id,
                    deployment_id=deployment_id,
                    slot_id=slot_id,
                    cohort=cohort,
                    ttl_anchor=ttl_anchor,
                )
                results["variants"][variant] = repl
            else:
                _append_event(
                    session,
                    observation_id=None,
                    uba_id=uba_id,
                    variant=variant,
                    event_type=EVT_WOULD_BLOCK,
                    observed_at=now,
                    symbol=sym,
                    selection_id=sel_id,
                    score=initial_score,
                    metadata={"reason": "SHADOW_CAPACITY_FULL"},
                )
                results["variants"][variant] = {
                    "ok": False,
                    "reason": "SHADOW_CAPACITY_FULL",
                    "would_admit": False,
                }
            continue

        row = UpbitWaitingLifecycleShadowObservationEntity(
            user_broker_account_id=uba_id,
            variant=variant,
            cohort=cohort,
            symbol=sym,
            selection_id=sel_id,
            candidate_id=int(candidate_id)
            if candidate_id is not None
            else sel_id,
            candidate_snapshot_id=candidate_snapshot_id,
            strategy_id=strategy_id,
            deployment_id=deployment_id,
            slot_id=slot_id,
            waiting_created_at=created,
            enrolled_at=now,
            ttl_anchor_at=ttl_anchor,
            initial_score=float(initial_score)
            if initial_score is not None
            else None,
            status=STATUS_ACTIVE,
            research_only=True,
            rule_version=RULE_VERSION,
            meta_json={"lab_id": LAB_ID},
        )
        session.add(row)
        session.flush()
        _append_event(
            session,
            observation_id=int(row.observation_id),
            uba_id=uba_id,
            variant=variant,
            event_type=EVT_ENROLLED,
            observed_at=now,
            age_seconds=0.0,
            symbol=sym,
            selection_id=sel_id,
            score=initial_score,
            metadata={"cohort": cohort},
            force=True,
        )
        _append_event(
            session,
            observation_id=int(row.observation_id),
            uba_id=uba_id,
            variant=variant,
            event_type=EVT_SHADOW_ADMITTED,
            observed_at=now,
            symbol=sym,
            selection_id=sel_id,
            score=initial_score,
            force=True,
        )
        results["variants"][variant] = {
            "ok": True,
            "observation_id": int(row.observation_id),
            "would_admit": True,
            "cohort": cohort,
        }
    return results


def _try_shadow_replace(
    session: Session,
    *,
    uba_id: int,
    new_symbol: str,
    new_selection_id: int,
    new_score: float | None,
    now: datetime,
    waiting_created_at: datetime,
    candidate_id: int | None,
    strategy_id: int | None,
    deployment_id: int | None,
    slot_id: int | None,
    cohort: str,
    ttl_anchor: datetime,
) -> dict[str, Any]:
    """R3 only — margin +10 vs lowest replacement-eligible stale/active."""

    pol = policy_for(VARIANT_R3)
    margin = float(pol.replacement_score_margin or 10.0)
    if new_score is None:
        _append_event(
            session,
            observation_id=None,
            uba_id=uba_id,
            variant=VARIANT_R3,
            event_type=EVT_WOULD_BLOCK,
            observed_at=now,
            symbol=new_symbol,
            selection_id=new_selection_id,
            metadata={"reason": "NO_SCORE"},
        )
        return {"ok": False, "reason": "NO_SCORE", "would_replace": False}

    actives = list(
        session.scalars(
            select(UpbitWaitingLifecycleShadowObservationEntity).where(
                UpbitWaitingLifecycleShadowObservationEntity.user_broker_account_id
                == uba_id,
                UpbitWaitingLifecycleShadowObservationEntity.variant
                == VARIANT_R3,
                UpbitWaitingLifecycleShadowObservationEntity.status.in_(
                    [STATUS_ACTIVE, STATUS_STALE]
                ),
            )
        )
    )
    eligible: list[UpbitWaitingLifecycleShadowObservationEntity] = []
    for row in actives:
        age = shadow_age_seconds(row, now=now)
        if age >= pol.soft_stale_seconds:
            if row.status == STATUS_ACTIVE:
                row.status = STATUS_STALE
                row.stale_at = row.stale_at or now
                _append_event(
                    session,
                    observation_id=int(row.observation_id),
                    uba_id=uba_id,
                    variant=VARIANT_R3,
                    event_type=EVT_STALE,
                    observed_at=now,
                    age_seconds=age,
                    symbol=row.symbol,
                    selection_id=int(row.selection_id),
                )
            _append_event(
                session,
                observation_id=int(row.observation_id),
                uba_id=uba_id,
                variant=VARIANT_R3,
                event_type=EVT_REPLACEMENT_ELIGIBLE,
                observed_at=now,
                age_seconds=age,
                score=row.initial_score,
                symbol=row.symbol,
                selection_id=int(row.selection_id),
            )
            eligible.append(row)

    if not eligible:
        _append_event(
            session,
            observation_id=None,
            uba_id=uba_id,
            variant=VARIANT_R3,
            event_type=EVT_WOULD_BLOCK,
            observed_at=now,
            symbol=new_symbol,
            selection_id=new_selection_id,
            score=new_score,
            metadata={"reason": "NO_REPLACEMENT_ELIGIBLE"},
        )
        return {
            "ok": False,
            "reason": "NO_REPLACEMENT_ELIGIBLE",
            "would_replace": False,
        }

    lowest = min(
        eligible,
        key=lambda r: float(r.initial_score)
        if r.initial_score is not None
        else float("inf"),
    )
    low_score = float(lowest.initial_score or 0.0)
    if float(new_score) < low_score + margin:
        _append_event(
            session,
            observation_id=int(lowest.observation_id),
            uba_id=uba_id,
            variant=VARIANT_R3,
            event_type=EVT_WOULD_BLOCK,
            observed_at=now,
            symbol=new_symbol,
            selection_id=new_selection_id,
            score=new_score,
            metadata={
                "reason": "INSUFFICIENT_SCORE_MARGIN",
                "lowest_score": low_score,
                "margin": margin,
                "needed": low_score + margin,
            },
        )
        return {
            "ok": False,
            "reason": "INSUFFICIENT_SCORE_MARGIN",
            "would_replace": False,
            "lowest_score": low_score,
            "new_score": float(new_score),
            "margin": margin,
        }

    # replace out
    lowest.status = STATUS_REPLACED
    lowest.replaced_at = now
    lowest.replacement_selection_id = int(new_selection_id)
    lowest.replacement_candidate_id = (
        int(candidate_id) if candidate_id is not None else int(new_selection_id)
    )
    lowest.replacement_score = float(new_score)
    lowest.terminal_stage = EVT_REPLACED
    _append_event(
        session,
        observation_id=int(lowest.observation_id),
        uba_id=uba_id,
        variant=VARIANT_R3,
        event_type=EVT_REPLACED,
        observed_at=now,
        age_seconds=shadow_age_seconds(lowest, now=now),
        score=float(new_score),
        symbol=lowest.symbol,
        selection_id=int(lowest.selection_id),
        metadata={
            "replacement_selection_id": int(new_selection_id),
            "replaced_out_score": low_score,
            "replacement_in_score": float(new_score),
        },
        force=True,
    )
    _append_event(
        session,
        observation_id=int(lowest.observation_id),
        uba_id=uba_id,
        variant=VARIANT_R3,
        event_type=EVT_WOULD_REPLACE,
        observed_at=now,
        score=float(new_score),
        symbol=new_symbol,
        selection_id=new_selection_id,
        force=True,
    )
    _append_event(
        session,
        observation_id=int(lowest.observation_id),
        uba_id=uba_id,
        variant=VARIANT_R3,
        event_type=EVT_WOULD_EXPIRE_EXISTING,
        observed_at=now,
        symbol=lowest.symbol,
        selection_id=int(lowest.selection_id),
        force=True,
    )

    # admit new
    new_row = UpbitWaitingLifecycleShadowObservationEntity(
        user_broker_account_id=uba_id,
        variant=VARIANT_R3,
        cohort=cohort,
        symbol=str(new_symbol).upper(),
        selection_id=int(new_selection_id),
        candidate_id=int(candidate_id)
        if candidate_id is not None
        else int(new_selection_id),
        strategy_id=strategy_id,
        deployment_id=deployment_id,
        slot_id=slot_id,
        waiting_created_at=waiting_created_at,
        enrolled_at=now,
        ttl_anchor_at=ttl_anchor,
        initial_score=float(new_score),
        status=STATUS_ACTIVE,
        research_only=True,
        rule_version=RULE_VERSION,
        meta_json={
            "lab_id": LAB_ID,
            "replaced_observation_id": int(lowest.observation_id),
        },
    )
    session.add(new_row)
    session.flush()
    _append_event(
        session,
        observation_id=int(new_row.observation_id),
        uba_id=uba_id,
        variant=VARIANT_R3,
        event_type=EVT_ENROLLED,
        observed_at=now,
        symbol=new_row.symbol,
        selection_id=int(new_selection_id),
        score=float(new_score),
        metadata={"via": "REPLACEMENT"},
        force=True,
    )
    _append_event(
        session,
        observation_id=int(new_row.observation_id),
        uba_id=uba_id,
        variant=VARIANT_R3,
        event_type=EVT_WOULD_ADMIT,
        observed_at=now,
        symbol=new_row.symbol,
        selection_id=int(new_selection_id),
        score=float(new_score),
        force=True,
    )
    return {
        "ok": True,
        "would_replace": True,
        "would_admit": True,
        "replaced_observation_id": int(lowest.observation_id),
        "observation_id": int(new_row.observation_id),
        "score_improvement": float(new_score) - low_score,
    }


def observe_evaluation(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    selection_id: int | None,
    decision: str | None,
    block_reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Telemetry/revalidation tick — TTL은 decision과 무관하게 진행 (R1+)."""

    if not shadow_enabled() or selection_id is None:
        return {"ok": False, "reason": "SKIP"}
    now = _aware(now) or _now()
    uba_id = int(user_broker_account_id)
    sym = str(symbol or "").upper()
    sel_id = int(selection_id)
    decision_u = str(decision or "").upper() or None
    updated = 0
    for variant in ALL_VARIANTS:
        row = _find_active(
            session, uba_id=uba_id, variant=variant, selection_id=sel_id
        )
        if row is None:
            continue
        age = shadow_age_seconds(row, now=now)
        row.last_decision = decision_u
        row.last_block_reason = block_reason
        row.last_evaluated_at = now
        row.evaluation_count = int(row.evaluation_count or 0) + 1
        # consecutive — R0 관측용 (R1+ absolute에는 영향 없음)
        if decision_u in {"BUY", "TECHNICAL_PASS"}:
            row.consecutive_no_signal = 0
        elif decision_u == "BLOCK" or block_reason:
            row.consecutive_no_signal = int(row.consecutive_no_signal or 0) + 1

        evt = EVT_EVALUATED
        if decision_u == "TECHNICAL_PASS":
            evt = EVT_TECHNICAL_PASS
        elif decision_u == "BLOCK" or block_reason:
            evt = EVT_TECHNICAL_BLOCK
        _append_event(
            session,
            observation_id=int(row.observation_id),
            uba_id=uba_id,
            variant=variant,
            event_type=evt,
            observed_at=now,
            age_seconds=age,
            decision=decision_u,
            block_reason=block_reason,
            symbol=sym,
            selection_id=sel_id,
        )
        _apply_lifecycle_gates(session, row=row, now=now)
        updated += 1
    return {"ok": True, "updated": updated}


def _apply_lifecycle_gates(
    session: Session,
    *,
    row: UpbitWaitingLifecycleShadowObservationEntity,
    now: datetime,
) -> None:
    if row.status in TERMINAL_STATUSES:
        return
    pol = policy_for(row.variant)
    age = shadow_age_seconds(row, now=now)
    uba_id = int(row.user_broker_account_id)

    # soft stale mark
    if age >= pol.soft_stale_seconds and row.status == STATUS_ACTIVE:
        row.status = STATUS_STALE
        row.stale_at = now
        _append_event(
            session,
            observation_id=int(row.observation_id),
            uba_id=uba_id,
            variant=row.variant,
            event_type=EVT_STALE,
            observed_at=now,
            age_seconds=age,
            symbol=row.symbol,
            selection_id=int(row.selection_id),
            force=True,
        )

    # absolute expiry (R1/R2/R3) — decision 무시
    if (
        pol.absolute_expiry_seconds is not None
        and age >= pol.absolute_expiry_seconds
    ):
        row.status = STATUS_EXPIRED
        row.expired_at = now
        row.terminal_stage = EVT_ABSOLUTE_EXPIRED
        _append_event(
            session,
            observation_id=int(row.observation_id),
            uba_id=uba_id,
            variant=row.variant,
            event_type=EVT_ABSOLUTE_EXPIRED,
            observed_at=now,
            age_seconds=age,
            decision=row.last_decision,
            block_reason=row.last_block_reason,
            symbol=row.symbol,
            selection_id=int(row.selection_id),
            force=True,
        )
        return

    # R0 REAL-style conjunction (관측만 — REAL slot 미변경)
    if row.variant == VARIANT_R0 and pol.consecutive_no_signal_threshold:
        from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.constants import (
            R0_HARD_EXPIRE_SECONDS,
        )

        thr = int(pol.consecutive_no_signal_threshold)
        decision = str(row.last_decision or "").upper()
        no_progress = decision not in {"BUY", "TECHNICAL_PASS"}
        consec = int(row.consecutive_no_signal or 0)
        hard_ok = (
            age >= R0_HARD_EXPIRE_SECONDS
            and consec >= thr
            and no_progress
        )
        soft_consec = (
            consec >= thr + 2
            and age >= pol.soft_stale_seconds
            and no_progress
        )
        if hard_ok or soft_consec:
            row.status = STATUS_EXPIRED
            row.expired_at = now
            row.terminal_stage = "R0_REAL_STYLE_RELEASE_ELIGIBLE"
            _append_event(
                session,
                observation_id=int(row.observation_id),
                uba_id=uba_id,
                variant=VARIANT_R0,
                event_type=EVT_ABSOLUTE_EXPIRED,
                observed_at=now,
                age_seconds=age,
                decision=decision,
                metadata={"shadow_only": True, "path": "R0_CONJUNCTION"},
                force=True,
            )


def observe_real_stage(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    selection_id: int | None,
    stage: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Link REAL ENTRY_PASS / SIGNAL / ORDER / BUY to shadow observations."""

    if not shadow_enabled() or selection_id is None:
        return {"ok": False, "reason": "SKIP"}
    now = _aware(now) or _now()
    uba_id = int(user_broker_account_id)
    sel_id = int(selection_id)
    stage_u = str(stage or "").upper()
    stage_map = {
        "ENTRY_PASS": EVT_ENTRY_PASS,
        "SIGNAL_EMITTED": EVT_SIGNAL_EMITTED,
        "ORDER_INTENT": EVT_ORDER_INTENT,
        "ORDER_INTENT_CREATED": EVT_ORDER_INTENT,
        "BUY_FILLED": EVT_BUY_FILLED,
    }
    evt = stage_map.get(stage_u)
    if evt is None:
        return {"ok": False, "reason": "UNKNOWN_STAGE"}

    touched = 0
    # active + already expired (for later-bought metric)
    rows = list(
        session.scalars(
            select(UpbitWaitingLifecycleShadowObservationEntity).where(
                UpbitWaitingLifecycleShadowObservationEntity.user_broker_account_id
                == uba_id,
                UpbitWaitingLifecycleShadowObservationEntity.selection_id
                == sel_id,
            )
        )
    )
    for row in rows:
        age = shadow_age_seconds(row, now=now)
        _append_event(
            session,
            observation_id=int(row.observation_id),
            uba_id=uba_id,
            variant=row.variant,
            event_type=evt,
            observed_at=now,
            age_seconds=age,
            symbol=str(symbol or row.symbol).upper(),
            selection_id=sel_id,
            force=evt == EVT_BUY_FILLED,
        )
        if evt == EVT_BUY_FILLED:
            row.real_buy_filled = True
            if row.status == STATUS_EXPIRED:
                row.shadow_expired_but_real_later_bought = True
                _append_event(
                    session,
                    observation_id=int(row.observation_id),
                    uba_id=uba_id,
                    variant=row.variant,
                    event_type=EVT_REAL_LATER_BOUGHT,
                    observed_at=now,
                    age_seconds=age,
                    symbol=row.symbol,
                    selection_id=sel_id,
                    force=True,
                )
            elif row.status not in {STATUS_REPLACED}:
                row.status = STATUS_SUCCESS_TERMINAL
                row.terminal_stage = EVT_BUY_FILLED
        touched += 1
    return {"ok": True, "touched": touched}


def observe_full_slot_block(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    selection_id: int | None,
    score: float | None = None,
    reason_code: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """REAL FULL_SLOT / NO_WAITING 차단 후보를 shadow 입력으로 관측."""

    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    now = _aware(now) or _now()
    uba_id = int(user_broker_account_id)
    sym = str(symbol or "").upper()
    sel_id = int(selection_id) if selection_id is not None else None

    # always record full-slot pressure event (deduped)
    for variant in SHADOW_SIM_VARIANTS:
        _append_event(
            session,
            observation_id=None,
            uba_id=uba_id,
            variant=variant,
            event_type=EVT_FULL_SLOT_BLOCK,
            observed_at=now,
            symbol=sym,
            selection_id=sel_id,
            score=score,
            block_reason=reason_code or "FULL_MARKET_NO_WAITING_SIGNAL_SLOT",
            metadata={"counterfactual": "natural_blocked_candidate"},
        )

    if sel_id is None or score is None:
        _append_event(
            session,
            observation_id=None,
            uba_id=uba_id,
            variant=VARIANT_R3,
            event_type=EVT_COUNTERFACTUAL_UNOBSERVABLE,
            observed_at=now,
            symbol=sym,
            selection_id=sel_id,
            metadata={"reason": "MISSING_SELECTION_OR_SCORE"},
            force=True,
        )
        return {"ok": True, "would_admit": None, "unobservable": True}

    # hypothetical admission into each sim variant
    return enroll_waiting_opportunity(
        session,
        user_broker_account_id=uba_id,
        symbol=sym,
        selection_id=sel_id,
        waiting_created_at=now,
        candidate_id=sel_id,
        initial_score=score,
        cohort=COHORT_PRIMARY_FORWARD,
        variants=SHADOW_SIM_VARIANTS,
        now=now,
    )


def tick_active_observations(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Periodic absolute TTL / stale gate — REAL slots untouched."""

    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    now = _aware(now) or _now()
    q = select(UpbitWaitingLifecycleShadowObservationEntity).where(
        UpbitWaitingLifecycleShadowObservationEntity.status.in_(
            [STATUS_ACTIVE, STATUS_STALE]
        )
    )
    if user_broker_account_id is not None:
        q = q.where(
            UpbitWaitingLifecycleShadowObservationEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    rows = list(session.scalars(q))
    for row in rows:
        _apply_lifecycle_gates(session, row=row, now=now)
    session.flush()
    return {"ok": True, "checked": len(rows)}


def enroll_preexisting_waiting_slots(
    session: Session,
    *,
    user_broker_account_id: int,
    slots: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Activation snapshot — PREEXISTING cohort (primary metrics 제외)."""

    now = _aware(now) or _now()
    enrolled = 0
    for s in slots:
        try:
            enroll_waiting_opportunity(
                session,
                user_broker_account_id=user_broker_account_id,
                symbol=str(s["symbol"]),
                selection_id=int(s["selection_id"]),
                waiting_created_at=_aware(s.get("waiting_created_at")) or now,
                candidate_id=s.get("candidate_id"),
                strategy_id=s.get("strategy_id"),
                deployment_id=s.get("deployment_id"),
                slot_id=s.get("slot_id"),
                initial_score=s.get("initial_score"),
                cohort=COHORT_PREEXISTING,
                now=now,
            )
            enrolled += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "waiting_lifecycle_shadow_preexisting_enroll_failed",
                error=str(exc)[:200],
            )
    return {"ok": True, "enrolled": enrolled, "cohort": COHORT_PREEXISTING}


def _pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] * (c - k) + s[c] * (k - f)


def summarize_waiting_lifecycle_lab(
    session: Session,
    *,
    user_broker_account_id: int = 1380,
    include_preexisting: bool = False,
) -> dict[str, Any]:
    """Admin research summary — no promotion recommendations."""

    uba_id = int(user_broker_account_id)
    now = _now()
    epoch = deployment_epoch(session)
    variants_out: dict[str, Any] = {}

    for variant in ALL_VARIANTS:
        q = select(UpbitWaitingLifecycleShadowObservationEntity).where(
            UpbitWaitingLifecycleShadowObservationEntity.user_broker_account_id
            == uba_id,
            UpbitWaitingLifecycleShadowObservationEntity.variant == variant,
        )
        if not include_preexisting:
            q = q.where(
                UpbitWaitingLifecycleShadowObservationEntity.cohort
                == COHORT_PRIMARY_FORWARD
            )
        rows = list(session.scalars(q))
        ages = [shadow_age_seconds(r, now=now) for r in rows if r.status in {STATUS_ACTIVE, STATUS_STALE}]
        scores = [
            float(r.initial_score)
            for r in rows
            if r.initial_score is not None
        ]
        primary_n = sum(
            1 for r in rows if r.cohort == COHORT_PRIMARY_FORWARD
        )
        terminal_relevant = sum(
            1
            for r in rows
            if r.cohort == COHORT_PRIMARY_FORWARD
            and r.status
            in {
                STATUS_EXPIRED,
                STATUS_REPLACED,
                STATUS_SUCCESS_TERMINAL,
                STATUS_STALE,
            }
        )

        def _cnt(status: str) -> int:
            return sum(1 for r in rows if r.status == status)

        evt_q = select(func.count()).select_from(
            UpbitWaitingLifecycleShadowEventEntity
        ).where(
            UpbitWaitingLifecycleShadowEventEntity.user_broker_account_id
            == uba_id,
            UpbitWaitingLifecycleShadowEventEntity.variant == variant,
        )

        def _evt(etype: str) -> int:
            return int(
                session.scalar(evt_q.where(
                    UpbitWaitingLifecycleShadowEventEntity.event_type == etype
                ))
                or 0
            )

        readiness = "표본 수집 중"
        if terminal_relevant >= STRONG_REVIEW_N:
            readiness = "Strong Review Ready"
        elif terminal_relevant >= EARLY_REVIEW_N:
            readiness = "Early Review Ready"

        variants_out[variant] = {
            "variant": variant,
            "forward_n": primary_n,
            "total_enrolled": len(rows),
            "active": _cnt(STATUS_ACTIVE),
            "stale": _cnt(STATUS_STALE),
            "expired": _cnt(STATUS_EXPIRED),
            "replaced": _cnt(STATUS_REPLACED),
            "success_terminal": _cnt(STATUS_SUCCESS_TERMINAL),
            "full_slot_block": _evt(EVT_FULL_SLOT_BLOCK),
            "would_admit": _evt(EVT_WOULD_ADMIT) + sum(
                1
                for r in rows
                if r.status
                in {
                    STATUS_ACTIVE,
                    STATUS_STALE,
                    STATUS_EXPIRED,
                    STATUS_SUCCESS_TERMINAL,
                    STATUS_REPLACED,
                }
            ),
            "would_replace": _evt(EVT_WOULD_REPLACE),
            "entry_pass": _evt(EVT_ENTRY_PASS),
            "signal_emitted": _evt(EVT_SIGNAL_EMITTED),
            "order_intent": _evt(EVT_ORDER_INTENT),
            "real_buy_filled": sum(1 for r in rows if r.real_buy_filled),
            "shadow_expired_but_real_later_bought": sum(
                1 for r in rows if r.shadow_expired_but_real_later_bought
            ),
            "counterfactual_unobservable": _evt(EVT_COUNTERFACTUAL_UNOBSERVABLE),
            "median_waiting_age_min": (
                round(statistics.median(ages) / 60.0, 2) if ages else None
            ),
            "p90_waiting_age_min": (
                round((_pct(ages, 0.9) or 0) / 60.0, 2) if ages else None
            ),
            "max_waiting_age_min": (
                round(max(ages) / 60.0, 2) if ages else None
            ),
            "average_admitted_score": (
                round(statistics.mean(scores), 2) if scores else None
            ),
            "slot_utilization": round(
                _active_count(session, uba_id=uba_id, variant=variant)
                / float(SHADOW_CAPACITY),
                3,
            ),
            "readiness": readiness,
            "terminal_relevant_n": terminal_relevant,
        }

    preexisting_n = int(
        session.scalar(
            select(func.count())
            .select_from(UpbitWaitingLifecycleShadowObservationEntity)
            .where(
                UpbitWaitingLifecycleShadowObservationEntity.user_broker_account_id
                == uba_id,
                UpbitWaitingLifecycleShadowObservationEntity.cohort
                == COHORT_PREEXISTING,
            )
        )
        or 0
    )

    early = any(
        v.get("terminal_relevant_n", 0) >= EARLY_REVIEW_N
        for v in variants_out.values()
    )
    strong = any(
        v.get("terminal_relevant_n", 0) >= STRONG_REVIEW_N
        for v in variants_out.values()
    )

    return {
        "ok": True,
        "lab_id": LAB_ID,
        "rule_version": RULE_VERSION,
        "research_only": True,
        "real_waiting_policy_unchanged": True,
        "real_policy_note": (
            "REAL: hard_expire=5400s AND consecutive>=3 AND decision not in "
            "{BUY,TECHNICAL_PASS} OR consecutive>=5 AND age>=soft_stale(1800s). "
            "Shadow R1/R2/R3 are research-only absolute TTL simulations."
        ),
        "uba_id": uba_id,
        "primary_forward_start": epoch.isoformat(),
        "preexisting_cohort_n": preexisting_n,
        "shadow_capacity": SHADOW_CAPACITY,
        "variants": variants_out,
        "early_review_ready": early,
        "strong_review_ready": strong,
        "comparison_note": (
            "Data only — no automatic promotion or policy change recommendation."
        ),
        "as_of": now.isoformat(),
    }


def list_observations(
    session: Session,
    *,
    user_broker_account_id: int = 1380,
    variant: str | None = None,
    cohort: str | None = None,
    status: str | None = None,
    symbol: str | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    uba_id = int(user_broker_account_id)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    filters = [
        UpbitWaitingLifecycleShadowObservationEntity.user_broker_account_id
        == uba_id
    ]
    if variant:
        filters.append(
            UpbitWaitingLifecycleShadowObservationEntity.variant
            == str(variant).upper()
        )
    if cohort:
        filters.append(
            UpbitWaitingLifecycleShadowObservationEntity.cohort == cohort
        )
    if status:
        filters.append(
            UpbitWaitingLifecycleShadowObservationEntity.status
            == str(status).upper()
        )
    if symbol:
        filters.append(
            UpbitWaitingLifecycleShadowObservationEntity.symbol
            == str(symbol).upper()
        )
    if from_at is not None:
        filters.append(
            UpbitWaitingLifecycleShadowObservationEntity.enrolled_at
            >= _aware(from_at)
        )
    if to_at is not None:
        filters.append(
            UpbitWaitingLifecycleShadowObservationEntity.enrolled_at
            <= _aware(to_at)
        )
    total = int(
        session.scalar(
            select(func.count())
            .select_from(UpbitWaitingLifecycleShadowObservationEntity)
            .where(and_(*filters))
        )
        or 0
    )
    rows = list(
        session.scalars(
            select(UpbitWaitingLifecycleShadowObservationEntity)
            .where(and_(*filters))
            .order_by(
                UpbitWaitingLifecycleShadowObservationEntity.enrolled_at.desc()
            )
            .offset(offset)
            .limit(limit)
        )
    )
    now = _now()
    items = []
    for r in rows:
        items.append(
            {
                "observation_id": int(r.observation_id),
                "variant": r.variant,
                "cohort": r.cohort,
                "symbol": r.symbol,
                "selection_id": int(r.selection_id),
                "status": r.status,
                "initial_score": r.initial_score,
                "waiting_created_at": r.waiting_created_at.isoformat()
                if r.waiting_created_at
                else None,
                "enrolled_at": r.enrolled_at.isoformat()
                if r.enrolled_at
                else None,
                "age_seconds": round(shadow_age_seconds(r, now=now), 1),
                "real_buy_filled": bool(r.real_buy_filled),
                "shadow_expired_but_real_later_bought": bool(
                    r.shadow_expired_but_real_later_bought
                ),
                "terminal_stage": r.terminal_stage,
            }
        )
    return {
        "ok": True,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


def compare_variants(
    session: Session, *, user_broker_account_id: int = 1380
) -> dict[str, Any]:
    summary = summarize_waiting_lifecycle_lab(
        session, user_broker_account_id=user_broker_account_id
    )
    variants = summary.get("variants") or {}
    r0 = variants.get(VARIANT_R0) or {}
    comparisons = []
    for v in SHADOW_SIM_VARIANTS:
        row = variants.get(v) or {}
        comparisons.append(
            {
                "variant": v,
                "vs_r0_expired_delta": (row.get("expired") or 0)
                - (r0.get("expired") or 0),
                "vs_r0_median_age_delta_min": (
                    None
                    if row.get("median_waiting_age_min") is None
                    or r0.get("median_waiting_age_min") is None
                    else round(
                        float(row["median_waiting_age_min"])
                        - float(r0["median_waiting_age_min"]),
                        2,
                    )
                ),
                "vs_r0_avg_score_delta": (
                    None
                    if row.get("average_admitted_score") is None
                    or r0.get("average_admitted_score") is None
                    else round(
                        float(row["average_admitted_score"])
                        - float(r0["average_admitted_score"]),
                        2,
                    )
                ),
                "full_slot_block": row.get("full_slot_block"),
                "would_admit": row.get("would_admit"),
                "real_buy_filled": row.get("real_buy_filled"),
                "expired_later_bought": row.get(
                    "shadow_expired_but_real_later_bought"
                ),
                "readiness": row.get("readiness"),
            }
        )
    return {
        "ok": True,
        "lab_id": LAB_ID,
        "real_waiting_policy_unchanged": True,
        "r0": r0,
        "comparisons": comparisons,
        "note": "Observation deltas only — no promote/recommend language.",
        "as_of": summary.get("as_of"),
    }
