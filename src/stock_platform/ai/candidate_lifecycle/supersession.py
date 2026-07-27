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

    previous = session.get(AICandidateLifecycleEntity, previous_candidate_id)
    if previous is None:
        blockers.append("PREVIOUS_LIFECYCLE_MISSING")

    replacement = session.get(AICandidateLifecycleEntity, replacement_candidate_id)
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
