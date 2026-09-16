"""STEP 11-13 — Candidate supersession helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.constants import SUPERSESSION_STATUS
from stock_platform.ai.candidate_lifecycle.entities import (
    AICandidateLifecycleEntity,
    AICandidateSupersessionEntity,
)


def find_active_supersession(
    session: Session,
    *,
    previous_candidate_id: int,
) -> AICandidateSupersessionEntity | None:
    """previous_candidate_id에 대한 ACTIVE supersession."""
    return session.scalar(
        select(AICandidateSupersessionEntity).where(
            AICandidateSupersessionEntity.previous_candidate_id
            == previous_candidate_id,
            AICandidateSupersessionEntity.supersession_status == "ACTIVE",
        )
    )


def validate_supersession_pair(
    session: Session,
    *,
    previous_candidate_id: int,
    replacement_candidate_id: int,
) -> dict[str, Any]:
    """Supersede 전 검증."""
    blockers: list[str] = []
    if previous_candidate_id == replacement_candidate_id:
        blockers.append("SAME_CANDIDATE")

    # STEP12-1A: candidate_lifecycle의 PK는 lifecycle_id이고 candidate_id는
    # 별도 UniqueConstraint 컬럼이다(strategy_request/service.py의 동일한
    # 주의사항 참고). session.get()은 PK 조회이므로 candidate_id를 넘기면
    # 엉뚱한(또는 존재하지 않는) 행을 조회해 PREVIOUS/REPLACEMENT_LIFECYCLE_
    # MISSING을 오탐하거나, 공교롭게 lifecycle_id와 값이 같은 무관한 행을
    # 반환할 수 있었다. candidate_id로 select() 조회하도록 수정.
    previous = session.scalar(
        select(AICandidateLifecycleEntity).where(
            AICandidateLifecycleEntity.candidate_id == previous_candidate_id
        )
    )
    if previous is None:
        blockers.append("PREVIOUS_LIFECYCLE_MISSING")

    replacement = session.scalar(
        select(AICandidateLifecycleEntity).where(
            AICandidateLifecycleEntity.candidate_id == replacement_candidate_id
        )
    )
    if replacement is None:
        blockers.append("REPLACEMENT_LIFECYCLE_MISSING")

    if find_active_supersession(
        session, previous_candidate_id=previous_candidate_id
    ):
        blockers.append("ACTIVE_SUPERSESSION_EXISTS")

    if replacement and replacement.lifecycle_status in {
        "REVOKED",
        "SUPERSEDED",
        "ARCHIVED",
    }:
        blockers.append("REPLACEMENT_NOT_ELIGIBLE")

    return {"allowed": not blockers, "blockers": blockers}


def build_supersession_entity(
    *,
    previous_candidate_id: int,
    replacement_candidate_id: int,
    requested_by: str,
    reason: str | None = None,
    correlation_id: str | None = None,
) -> AICandidateSupersessionEntity:
    status = "ACTIVE"
    if status not in SUPERSESSION_STATUS:
        raise ValueError(f"invalid supersession status {status}")
    return AICandidateSupersessionEntity(
        previous_candidate_id=previous_candidate_id,
        replacement_candidate_id=replacement_candidate_id,
        supersession_status=status,
        reason=reason,
        requested_by=requested_by,
        correlation_id=correlation_id,
    )
