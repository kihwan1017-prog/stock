"""Scheduler auto-Recovery 대상 분류 (SHARED).

periodic job 은 healthy SUCCESS 에 full Recovery 를 하지 않는다.
failed_retry 만 FAILED+eligible 을 targeted Recovery 한다.
manual/admin recover_all 계약은 이 모듈을 우회한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_conflict_constants import (
    ACTIVE_REVIEW_STATUSES,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.trading.account_models import (
    PaperAccount,
    UserBrokerAccount,
)

# credential/정책상 자동 재시도 금지 (scheduler_service 와 동일 집합)
NON_RETRYABLE_ERROR_CODES = frozenset(
    {
        "credential_missing",
        "credential_invalid",
        "credential_decryption_failed",
        "credential_expired",
        "credential_broker_mismatch",
        "credential_unverified",
        "vault_unavailable",
        "manual_review_required",
        "account_inactive",
        "account_paused",
    }
)


class AutoRecoveryDecision(StrEnum):
    RECOVERY_ELIGIBLE = "RECOVERY_ELIGIBLE"
    SKIP_HEALTHY = "SKIP_HEALTHY"
    SKIP_RECENT = "SKIP_RECENT"
    SKIP_CREDENTIAL = "SKIP_CREDENTIAL"
    SKIP_CONFLICT = "SKIP_CONFLICT"
    SKIP_MANUAL_REVIEW = "SKIP_MANUAL_REVIEW"
    SKIP_LIVE = "SKIP_LIVE"
    SKIP_ARMED = "SKIP_ARMED"
    SKIP_INACTIVE = "SKIP_INACTIVE"
    SKIP_NOT_DUE = "SKIP_NOT_DUE"
    SKIP_IN_PROGRESS = "SKIP_IN_PROGRESS"
    LOCAL_FINALIZE_EXPIRED = "LOCAL_FINALIZE_EXPIRED"
    CHECK_ONLY = "CHECK_ONLY"


# SUCCESS 직후 periodic 재시도 금지 여유 (초) — broker READ 없이 updated_at 기준
DEFAULT_RECENT_SUCCESS_SECONDS = 3600


@dataclass(frozen=True)
class AccountSafetySnapshot:
    """selector 입력 — DB/테스트 fixture 공용."""

    broker_code: str
    user_broker_account_id: int | None = None
    paper_account_id: int | None = None
    recovery_status: str | None = None
    auto_retry_enabled: bool = True
    next_retry_at: datetime | None = None
    last_error_code: str | None = None
    lock_expires_at: datetime | None = None
    updated_at: datetime | None = None
    is_active: bool = True
    live_order_enabled: bool = False
    live_armed: bool = False
    has_open_high_conflict: bool = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _norm_status(value: str | None) -> str:
    return str(value or "").strip().upper()


def classify_auto_recovery_target(
    snap: AccountSafetySnapshot,
    *,
    mode: str,
    now: datetime | None = None,
    recent_success_seconds: int = DEFAULT_RECENT_SUCCESS_SECONDS,
) -> AutoRecoveryDecision:
    """자동 Scheduler 대상 분류 — ambiguous 는 fail-closed (CHECK_ONLY/SKIP)."""

    current = now or _utcnow()
    status = _norm_status(snap.recovery_status)
    job_mode = str(mode or "").strip().lower()

    if not snap.is_active:
        return AutoRecoveryDecision.SKIP_INACTIVE

    # Paper 는 LIVE/ARM 필드 없음 — UBA 만
    if snap.user_broker_account_id is not None:
        if snap.live_order_enabled:
            return AutoRecoveryDecision.SKIP_LIVE
        if snap.live_armed:
            return AutoRecoveryDecision.SKIP_ARMED

    if status == "MANUAL_REVIEW":
        return AutoRecoveryDecision.SKIP_MANUAL_REVIEW

    if snap.has_open_high_conflict:
        return AutoRecoveryDecision.SKIP_CONFLICT

    err = str(snap.last_error_code or "").strip().lower()
    if err and err in NON_RETRYABLE_ERROR_CODES:
        return AutoRecoveryDecision.SKIP_CREDENTIAL

    if status == "RUNNING":
        expires = snap.lock_expires_at
        if expires is not None and expires <= current:
            return AutoRecoveryDecision.LOCAL_FINALIZE_EXPIRED
        # TTL 없거나 미만료 → 진행 중/모호 — fail-closed
        return AutoRecoveryDecision.SKIP_IN_PROGRESS

    if job_mode == "failed_retry":
        if status != "FAILED":
            if status in {"SUCCESS", "IDLE", ""}:
                return AutoRecoveryDecision.SKIP_HEALTHY
            return AutoRecoveryDecision.SKIP_NOT_DUE
        if not snap.auto_retry_enabled:
            return AutoRecoveryDecision.SKIP_NOT_DUE
        if snap.next_retry_at is None or snap.next_retry_at > current:
            return AutoRecoveryDecision.SKIP_NOT_DUE
        return AutoRecoveryDecision.RECOVERY_ELIGIBLE

    # periodic (upbit/kiwoom/paper): full Recovery 금지 · FAILED 는 failed_retry 전담
    if status == "SUCCESS":
        if (
            snap.updated_at is not None
            and (current - snap.updated_at).total_seconds()
            < max(0, int(recent_success_seconds))
        ):
            return AutoRecoveryDecision.SKIP_RECENT
        return AutoRecoveryDecision.SKIP_HEALTHY

    if status in {"FAILED", "IDLE", ""}:
        return AutoRecoveryDecision.CHECK_ONLY

    return AutoRecoveryDecision.CHECK_ONLY


def has_open_high_conflict(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
    paper_account_id: int | None = None,
    broker_code: str | None = None,
) -> bool:
    """활성 검토 + HIGH risk Conflict 존재 여부."""

    stmt = select(BrokerRecoveryConflictEntity.broker_recovery_conflict_id).where(
        BrokerRecoveryConflictEntity.review_status.in_(
            tuple(ACTIVE_REVIEW_STATUSES)
        ),
        BrokerRecoveryConflictEntity.risk_level == "HIGH",
    )
    if user_broker_account_id is not None:
        stmt = stmt.where(
            BrokerRecoveryConflictEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    elif paper_account_id is not None:
        stmt = stmt.where(
            BrokerRecoveryConflictEntity.paper_account_id
            == int(paper_account_id)
        )
    else:
        return False
    if broker_code:
        stmt = stmt.where(
            BrokerRecoveryConflictEntity.broker_code
            == str(broker_code).upper()
        )
    return session.scalar(stmt.limit(1)) is not None


def load_uba_safety(
    session: Session, uba_id: int
) -> tuple[bool, bool, bool]:
    """(is_active, live_order_enabled, live_armed)."""

    row = session.get(UserBrokerAccount, int(uba_id))
    if row is None:
        return False, False, False
    return (
        bool(row.is_active),
        bool(getattr(row, "live_order_enabled", False)),
        bool(getattr(row, "live_armed", False)),
    )


def load_paper_active(session: Session, paper_id: int) -> bool:
    row = session.get(PaperAccount, int(paper_id))
    if row is None:
        return False
    return bool(row.is_active) and getattr(row, "deleted_at", None) is None


def build_snapshot_from_state(
    session: Session,
    state: BrokerRecoveryAccountStateEntity,
) -> AccountSafetySnapshot:
    uba_id = state.user_broker_account_id
    paper_id = state.paper_account_id
    is_active = True
    live_on = False
    armed = False
    if uba_id is not None:
        is_active, live_on, armed = load_uba_safety(session, int(uba_id))
    elif paper_id is not None:
        is_active = load_paper_active(session, int(paper_id))

    conflict = has_open_high_conflict(
        session,
        user_broker_account_id=int(uba_id) if uba_id is not None else None,
        paper_account_id=int(paper_id) if paper_id is not None else None,
        broker_code=state.broker_code,
    )
    return AccountSafetySnapshot(
        broker_code=str(state.broker_code or "").upper(),
        user_broker_account_id=(
            int(uba_id) if uba_id is not None else None
        ),
        paper_account_id=int(paper_id) if paper_id is not None else None,
        recovery_status=state.recovery_status,
        auto_retry_enabled=bool(state.auto_retry_enabled),
        next_retry_at=state.next_retry_at,
        last_error_code=state.last_error_code,
        lock_expires_at=state.lock_expires_at,
        updated_at=state.updated_at,
        is_active=is_active,
        live_order_enabled=live_on,
        live_armed=armed,
        has_open_high_conflict=conflict,
    )


def list_failed_retry_targets(
    session: Session,
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """FAILED+due 후보를 안전 gate 통과분만 반환."""

    current = now or _utcnow()
    stmt = select(BrokerRecoveryAccountStateEntity).where(
        BrokerRecoveryAccountStateEntity.auto_retry_enabled.is_(True),
        BrokerRecoveryAccountStateEntity.recovery_status == "FAILED",
        BrokerRecoveryAccountStateEntity.next_retry_at.is_not(None),
        BrokerRecoveryAccountStateEntity.next_retry_at <= current,
    )
    eligible: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in session.scalars(stmt):
        snap = build_snapshot_from_state(session, row)
        decision = classify_auto_recovery_target(
            snap, mode="failed_retry", now=current
        )
        payload = {
            "broker_code": snap.broker_code,
            "user_broker_account_id": snap.user_broker_account_id,
            "paper_account_id": snap.paper_account_id,
            "user_id": row.user_id,
            "retry_count": row.retry_count,
            "decision": str(decision),
        }
        if decision == AutoRecoveryDecision.RECOVERY_ELIGIBLE:
            eligible.append(payload)
        else:
            skipped.append(payload)
    return eligible, skipped


def broker_codes_for_job(broker_filter: str | None) -> list[str] | None:
    """finalize SQL 용 broker_code 목록. None = 전체."""

    if not broker_filter:
        return None
    code = str(broker_filter).upper()
    if code == "PAPER":
        return ["PAPER", "PAPER_STOCK", "PAPER_CRYPTO"]
    if code in {"PAPER_STOCK", "PAPER_CRYPTO", "KIWOOM", "UPBIT"}:
        return [code]
    return [code]


def summarize_periodic_decisions(
    session: Session,
    *,
    broker_filter: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """periodic tick 분류 요약 — Recovery 대상 목록은 비운다."""

    current = now or _utcnow()
    codes = broker_codes_for_job(broker_filter)
    stmt = select(BrokerRecoveryAccountStateEntity)
    if codes is not None:
        stmt = stmt.where(
            BrokerRecoveryAccountStateEntity.broker_code.in_(codes)
        )
    decisions: dict[str, int] = {}
    finalize_candidates = 0
    for row in session.scalars(stmt):
        snap = build_snapshot_from_state(session, row)
        decision = classify_auto_recovery_target(
            snap, mode="periodic", now=current
        )
        key = str(decision)
        decisions[key] = int(decisions.get(key) or 0) + 1
        if decision == AutoRecoveryDecision.LOCAL_FINALIZE_EXPIRED:
            finalize_candidates += 1
    return {
        "decision_counts": decisions,
        "finalize_candidates": finalize_candidates,
        "recovery_eligible_count": 0,
    }
