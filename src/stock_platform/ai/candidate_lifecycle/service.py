"""STEP 11-13 — Candidate Lifecycle Service.

Critical safety:
- candidate_id = strategy.candidate_result.result_id
- Only promotion-created candidates (candidate_promotion_link) get lifecycle rows
- No AI calls, no strategy/runtime/order/broker/scheduler WRITE imports
- Expire/revoke = status only; no hard delete
- Revalidation = fingerprint compare only
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.constants import (
    ACTIVE_REVOCATION_STATUSES,
    LIFECYCLE_STATUS,
    REFERENCE_DISCLAIMER,
    TERMINAL_LIFECYCLE_STATUSES,
)
from stock_platform.ai.candidate_lifecycle.entities import (
    AICandidateLifecycleEntity,
    AICandidateLifecycleHistoryEntity,
    AICandidateProvenanceSnapshotEntity,
    AICandidateRevalidationEntity,
    AICandidateRevocationEntity,
)
from stock_platform.ai.candidate_lifecycle.expiration import (
    compute_expiration_at,
    is_expired,
)
from stock_platform.ai.candidate_lifecycle.health import compute_health
from stock_platform.ai.candidate_lifecycle.provenance import (
    build_provenance_snapshot,
    build_source_graph,
)
from stock_platform.ai.candidate_lifecycle.revalidation import compare_fingerprints
from stock_platform.ai.candidate_lifecycle.revocation import check_revocation_blockers
from stock_platform.ai.candidate_lifecycle.supersession import (
    build_supersession_entity,
    validate_supersession_pair,
)
from stock_platform.ai.candidate_lifecycle.transitions import can_transition
from stock_platform.ai.candidate_promotion.entities import (
    AICandidatePromotionLinkEntity,
    AICandidatePromotionRequestEntity,
)
from stock_platform.ai.candidate_recommendation_queue.entities import (
    AICandidateRecommendationQueueEntity,
)
from stock_platform.ai.providers.security import mask_pii


class AICandidateLifecycleError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _revalidation_key(candidate_id: int, *, suffix: str | None = None) -> str:
    raw = f"lifecycle-revalidation:{candidate_id}:{suffix or uuid.uuid4().hex}"
    return hashlib.sha256(raw.encode()).hexdigest()[:220]


def _revocation_key(candidate_id: int, *, suffix: str | None = None) -> str:
    raw = f"lifecycle-revocation:{candidate_id}:{suffix or uuid.uuid4().hex}"
    return hashlib.sha256(raw.encode()).hexdigest()[:220]


class AICandidateLifecycleService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _get_lifecycle(
        self,
        candidate_id: int,
        *,
        for_update: bool = False,
    ) -> AICandidateLifecycleEntity:
        stmt = select(AICandidateLifecycleEntity).where(
            AICandidateLifecycleEntity.candidate_id == candidate_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        row = self._session.scalar(stmt)
        if row is None:
            raise AICandidateLifecycleError(
                "NOT_FOUND", f"lifecycle for candidate {candidate_id} missing"
            )
        return row

    def _check_version(
        self,
        row: AICandidateLifecycleEntity,
        expected_version: int | None,
    ) -> None:
        if expected_version is not None and row.lifecycle_version != expected_version:
            raise AICandidateLifecycleError(
                "VERSION_CONFLICT",
                f"expected version {expected_version}, got {row.lifecycle_version}",
            )

    def _bump_version(self, row: AICandidateLifecycleEntity, actor: str) -> None:
        row.lifecycle_version = (row.lifecycle_version or 0) + 1
        row.updated_at = _now()
        row.updated_by = actor

    def _history(
        self,
        candidate_id: int,
        *,
        action: str,
        actor: str,
        previous_lifecycle: str | None = None,
        new_lifecycle: str | None = None,
        previous_health: str | None = None,
        new_health: str | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self._session.add(
            AICandidateLifecycleHistoryEntity(
                candidate_id=candidate_id,
                action=action,
                previous_lifecycle_status=previous_lifecycle,
                new_lifecycle_status=new_lifecycle,
                previous_health_status=previous_health,
                new_health_status=new_health,
                reason=reason,
                requested_by=actor,
                correlation_id=correlation_id,
            )
        )

    def _transition(
        self,
        row: AICandidateLifecycleEntity,
        *,
        new_status: str,
        actor: str,
        action: str,
        reason: str | None = None,
        reason_code: str | None = None,
        correlation_id: str | None = None,
        expected_version: int | None = None,
    ) -> None:
        if new_status not in LIFECYCLE_STATUS:
            raise AICandidateLifecycleError(
                "INVALID_STATUS", f"bad lifecycle status {new_status}"
            )
        self._check_version(row, expected_version)
        if not can_transition(row.lifecycle_status, new_status):
            raise AICandidateLifecycleError(
                "INVALID_TRANSITION",
                f"cannot transition {row.lifecycle_status} -> {new_status}",
            )
        prev_lifecycle = row.lifecycle_status
        prev_health = row.health_status
        row.lifecycle_status = new_status
        self._bump_version(row, actor)
        if reason_code:
            row.status_reason_code = reason_code
        if reason:
            # STEP12-1A: sanitize_for_log()는 dict payload용 시크릿 마스킹
            # 함수라 문자열 reason에 호출하면 payload.items()에서
            # AttributeError가 발생했다(expire/supersede 등 reason이 있는
            # 모든 전이가 항상 실패). 자유 텍스트용 mask_pii()로 교체.
            row.status_reason_message = mask_pii(reason)[:2000]
        row.health_status = compute_health(row)
        self._history(
            row.candidate_id,
            action=action,
            actor=actor,
            previous_lifecycle=prev_lifecycle,
            new_lifecycle=new_status,
            previous_health=prev_health,
            new_health=row.health_status,
            reason=reason,
            correlation_id=correlation_id,
        )

    def _refresh_health(self, row: AICandidateLifecycleEntity, actor: str) -> None:
        prev = row.health_status
        row.health_status = compute_health(row)
        if prev != row.health_status:
            self._history(
                row.candidate_id,
                action="HEALTH_UPDATED",
                actor=actor,
                previous_health=prev,
                new_health=row.health_status,
            )

    def _promotion_link(
        self, candidate_id: int
    ) -> tuple[
        AICandidatePromotionLinkEntity,
        AICandidatePromotionRequestEntity,
        AICandidateRecommendationQueueEntity | None,
    ]:
        link = self._session.scalar(
            select(AICandidatePromotionLinkEntity).where(
                AICandidatePromotionLinkEntity.candidate_result_id == candidate_id
            )
        )
        if link is None:
            raise AICandidateLifecycleError(
                "NOT_PROMOTED",
                f"candidate {candidate_id} has no promotion link",
            )
        request = self._session.get(
            AICandidatePromotionRequestEntity, link.promotion_request_id
        )
        if request is None:
            raise AICandidateLifecycleError(
                "NOT_FOUND", f"promotion request for candidate {candidate_id} missing"
            )
        queue = self._session.get(
            AICandidateRecommendationQueueEntity, link.queue_id
        )
        return link, request, queue

    def _link_meta(self, candidate_id: int) -> dict[str, int | None]:
        """candidate_promotion_link에서 promotion_request_id·queue_id (null-safe)."""
        link = self._session.scalar(
            select(AICandidatePromotionLinkEntity).where(
                AICandidatePromotionLinkEntity.candidate_result_id == candidate_id
            )
        )
        if link is None:
            return {"promotion_request_id": None, "queue_id": None}
        return {
            "promotion_request_id": link.promotion_request_id,
            "queue_id": link.queue_id,
        }

    def _public(self, row: AICandidateLifecycleEntity) -> dict[str, Any]:
        link_meta = self._link_meta(row.candidate_id)
        return {
            "candidate_id": row.candidate_id,
            "lifecycle_status": row.lifecycle_status,
            "health_status": row.health_status,
            "lifecycle_version": row.lifecycle_version,
            "source_fingerprint": row.source_fingerprint,
            "source_changed": row.source_changed,
            "revalidation_required": row.revalidation_required,
            "expiration_at": (
                row.expiration_at.isoformat() if row.expiration_at else None
            ),
            "expired_at": row.expired_at.isoformat() if row.expired_at else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            "superseded_at": (
                row.superseded_at.isoformat() if row.superseded_at else None
            ),
            "archived_at": row.archived_at.isoformat() if row.archived_at else None,
            "last_validated_at": (
                row.last_validated_at.isoformat() if row.last_validated_at else None
            ),
            "last_revalidated_at": (
                row.last_revalidated_at.isoformat()
                if row.last_revalidated_at
                else None
            ),
            "status_reason_code": row.status_reason_code,
            "status_reason_message": row.status_reason_message,
            "promotion_request_id": link_meta["promotion_request_id"],
            "queue_id": link_meta["queue_id"],
            "created_by": row.created_by,
            "updated_by": row.updated_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def ensure_lifecycle(
        self,
        candidate_id: int,
        *,
        actor: str = "system",
    ) -> dict[str, Any]:
        """
        Promotion link가 있는 candidate에 lifecycle row 보장.

        API layer commits — session.flush() only.
        """
        existing = self._session.scalar(
            select(AICandidateLifecycleEntity).where(
                AICandidateLifecycleEntity.candidate_id == candidate_id
            )
        )
        if existing is not None:
            return {"created": False, "lifecycle": self._public(existing)}

        link, request, queue = self._promotion_link(candidate_id)
        if request.promotion_status != "COMPLETED":
            raise AICandidateLifecycleError(
                "NOT_PROMOTED",
                f"promotion not completed for candidate {candidate_id}",
            )

        committed_at = request.committed_at or link.promoted_at or _now()
        expiration_at = compute_expiration_at(
            market_type=request.market_type,
            committed_at=committed_at,
        )
        source_fp = request.source_result_hash or link.candidate_result_hash
        health = "HEALTHY" if source_fp and link.candidate_result_hash else "UNKNOWN"

        row = AICandidateLifecycleEntity(
            candidate_id=candidate_id,
            lifecycle_status="PROMOTED",
            health_status=health,
            source_fingerprint=source_fp,
            expiration_at=expiration_at,
            last_validated_at=committed_at,
            created_by=link.promoted_by,
            updated_by=actor,
        )
        self._session.add(row)
        self._session.flush()

        snapshot = build_provenance_snapshot(
            session=self._session,
            candidate_id=candidate_id,
            promotion_request=request,
            promotion_link=link,
            queue=queue,
        )
        self._session.add(snapshot)

        self._history(
            candidate_id,
            action="LIFECYCLE_CREATED",
            actor=actor,
            new_lifecycle="PROMOTED",
            new_health=health,
            reason="promotion link ensure",
        )
        self._session.flush()
        return {"created": True, "lifecycle": self._public(row)}

    def get(self, candidate_id: int) -> dict[str, Any]:
        row = self._get_lifecycle(candidate_id)
        return {"lifecycle": self._public(row)}

    def list_lifecycles(
        self,
        *,
        lifecycle_status: str | None = None,
        health_status: str | None = None,
        revalidation_required: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        stmt = select(AICandidateLifecycleEntity).order_by(
            AICandidateLifecycleEntity.created_at.desc()
        )
        if lifecycle_status:
            stmt = stmt.where(
                AICandidateLifecycleEntity.lifecycle_status == lifecycle_status
            )
        if health_status:
            stmt = stmt.where(
                AICandidateLifecycleEntity.health_status == health_status
            )
        if revalidation_required is not None:
            stmt = stmt.where(
                AICandidateLifecycleEntity.revalidation_required
                == revalidation_required
            )
        total = self._session.scalar(
            select(func.count()).select_from(stmt.subquery())
        )
        rows = self._session.scalars(stmt.limit(limit).offset(offset)).all()
        return {
            "items": [self._public(r) for r in rows],
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def activate_review(
        self,
        candidate_id: int,
        *,
        expected_version: int,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_lifecycle(candidate_id, for_update=True)
        self._transition(
            row,
            new_status="ACTIVE_REVIEW",
            actor=actor,
            action="REVIEW_ACTIVATED",
            reason=reason,
            correlation_id=correlation_id,
            expected_version=expected_version,
        )
        self._session.flush()
        return {"lifecycle": self._public(row)}

    def validate(
        self,
        candidate_id: int,
        *,
        expected_version: int,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Fingerprint 일치 여부로 validate (AI 없음)."""
        row = self._get_lifecycle(candidate_id, for_update=True)
        self._check_version(row, expected_version)

        snapshot = self._session.scalar(
            select(AICandidateProvenanceSnapshotEntity).where(
                AICandidateProvenanceSnapshotEntity.candidate_id == candidate_id
            )
        )
        if snapshot is None:
            raise AICandidateLifecycleError(
                "PROVENANCE_MISSING", "provenance snapshot missing"
            )

        link, request, queue = self._promotion_link(candidate_id)
        current_graph = build_source_graph(
            session=self._session,
            promotion_request=request,
            promotion_link=link,
            queue=queue,
        )
        from stock_platform.ai.candidate_lifecycle.provenance import (
            build_combined_fingerprint,
        )

        actual_fp = build_combined_fingerprint(current_graph)
        expected_fp = snapshot.combined_source_fingerprint or row.source_fingerprint
        result = compare_fingerprints(expected=expected_fp, actual=actual_fp)

        now = _now()
        row.last_validated_at = now
        row.source_changed = not result["matched"]
        row.revalidation_required = not result["matched"]

        if result["matched"]:
            target_status = "PROMOTED"
            row.health_status = "HEALTHY"
        else:
            target_status = "REVALIDATION_REQUIRED"
            row.health_status = "REVALIDATION_REQUIRED"

        if can_transition(row.lifecycle_status, target_status):
            self._transition(
                row,
                new_status=target_status,
                actor=actor,
                action="VALIDATED",
                reason=reason,
                reason_code=result["status"],
                correlation_id=correlation_id,
                expected_version=expected_version,
            )
        else:
            self._bump_version(row, actor)
            self._refresh_health(row, actor)
            self._history(
                candidate_id,
                action="VALIDATED",
                actor=actor,
                reason=reason,
                correlation_id=correlation_id,
            )

        self._session.flush()
        return {
            "lifecycle": self._public(row),
            "validation": result,
        }

    def revalidate(
        self,
        candidate_id: int,
        *,
        expected_version: int,
        actor: str,
        reason: str,
        revalidation_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Fingerprint compare revalidation (AI 없음)."""
        row = self._get_lifecycle(candidate_id, for_update=True)
        self._check_version(row, expected_version)

        key = revalidation_key or _revalidation_key(candidate_id)
        existing = self._session.scalar(
            select(AICandidateRevalidationEntity).where(
                AICandidateRevalidationEntity.candidate_id == candidate_id,
                AICandidateRevalidationEntity.revalidation_key == key,
            )
        )
        if existing is not None and existing.revalidation_status in {
            "PASSED",
            "PASSED_WITH_WARNING",
            "FAILED",
            "CANCELLED",
        }:
            return {
                "idempotent_replay": True,
                "revalidation": self._public_revalidation(existing),
                "lifecycle": self._public(row),
            }

        snapshot = self._session.scalar(
            select(AICandidateProvenanceSnapshotEntity).where(
                AICandidateProvenanceSnapshotEntity.candidate_id == candidate_id
            )
        )
        if snapshot is None:
            raise AICandidateLifecycleError("PROVENANCE_MISSING", "no snapshot")

        link, request, queue = self._promotion_link(candidate_id)
        current_graph = build_source_graph(
            session=self._session,
            promotion_request=request,
            promotion_link=link,
            queue=queue,
        )
        from stock_platform.ai.candidate_lifecycle.provenance import (
            build_combined_fingerprint,
        )

        expected_fp = snapshot.combined_source_fingerprint or row.source_fingerprint
        actual_fp = build_combined_fingerprint(current_graph)
        result = compare_fingerprints(expected=expected_fp, actual=actual_fp)

        now = _now()
        rev = existing or AICandidateRevalidationEntity(
            candidate_id=candidate_id,
            revalidation_key=key,
            requested_by=actor,
            reason=reason,
            correlation_id=correlation_id,
        )
        rev.revalidation_status = "RUNNING"
        rev.started_at = now
        rev.expected_fingerprint = expected_fp
        rev.actual_fingerprint = actual_fp
        rev.fingerprint_match = result["matched"]
        rev.warnings = result.get("warnings")
        rev.revalidation_status = result["status"]
        rev.completed_at = now
        rev.completed_by = actor
        if existing is None:
            self._session.add(rev)

        row.last_revalidated_at = now
        row.source_changed = not result["matched"]
        row.revalidation_required = not result["matched"]

        if result["matched"]:
            row.health_status = "HEALTHY" if not result.get("warnings") else "WARNING"
            if can_transition(row.lifecycle_status, "PROMOTED"):
                self._transition(
                    row,
                    new_status="PROMOTED",
                    actor=actor,
                    action="REVALIDATED",
                    reason=reason,
                    correlation_id=correlation_id,
                    expected_version=expected_version,
                )
            else:
                self._bump_version(row, actor)
                self._refresh_health(row, actor)
        else:
            row.health_status = "REVALIDATION_REQUIRED"
            if can_transition(row.lifecycle_status, "REVALIDATION_REQUIRED"):
                self._transition(
                    row,
                    new_status="REVALIDATION_REQUIRED",
                    actor=actor,
                    action="REVALIDATION_FAILED",
                    reason=reason,
                    correlation_id=correlation_id,
                    expected_version=expected_version,
                )
            else:
                self._bump_version(row, actor)

        self._session.flush()
        return {
            "idempotent_replay": False,
            "revalidation": self._public_revalidation(rev),
            "lifecycle": self._public(row),
            "comparison": result,
        }

    def expire(
        self,
        candidate_id: int,
        *,
        expected_version: int,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_lifecycle(candidate_id, for_update=True)
        now = _now()
        row.expired_at = now
        self._transition(
            row,
            new_status="EXPIRED",
            actor=actor,
            action="EXPIRED",
            reason=reason,
            reason_code="MANUAL_OR_POLICY",
            correlation_id=correlation_id,
            expected_version=expected_version,
        )
        row.health_status = compute_health(row)
        self._session.flush()
        return {"lifecycle": self._public(row)}

    def request_revocation(
        self,
        candidate_id: int,
        *,
        expected_version: int,
        actor: str,
        reason: str,
        revocation_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_lifecycle(candidate_id, for_update=True)
        self._check_version(row, expected_version)

        if row.lifecycle_status in TERMINAL_LIFECYCLE_STATUSES:
            raise AICandidateLifecycleError(
                "INVALID_STATE", f"cannot revoke from {row.lifecycle_status}"
            )

        key = revocation_key or _revocation_key(candidate_id)
        existing = self._session.scalar(
            select(AICandidateRevocationEntity).where(
                AICandidateRevocationEntity.candidate_id == candidate_id,
                AICandidateRevocationEntity.revocation_key == key,
            )
        )
        if existing is not None:
            return {
                "idempotent_replay": True,
                "revocation": self._public_revocation(existing),
                "lifecycle": self._public(row),
            }

        blocker_result = check_revocation_blockers(
            self._session, candidate_id=candidate_id
        )
        now = _now()
        status = "BLOCKED" if blocker_result["blocked"] else "REQUESTED"
        rev = AICandidateRevocationEntity(
            candidate_id=candidate_id,
            revocation_key=key,
            revocation_status=status,
            blocked_reasons=blocker_result["blockers"],
            requested_by=actor,
            reason=reason,
            correlation_id=correlation_id,
            requested_at=now,
        )
        self._session.add(rev)

        if can_transition(row.lifecycle_status, "REVOCATION_REQUESTED"):
            self._transition(
                row,
                new_status="REVOCATION_REQUESTED",
                actor=actor,
                action="REVOCATION_REQUESTED",
                reason=reason,
                correlation_id=correlation_id,
                expected_version=expected_version,
            )
        else:
            self._bump_version(row, actor)

        self._session.flush()
        return {
            "idempotent_replay": False,
            "revocation": self._public_revocation(rev),
            "lifecycle": self._public(row),
            "blockers": blocker_result["blockers"],
        }

    def approve_revocation(
        self,
        candidate_id: int,
        *,
        revocation_key: str,
        expected_version: int,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_lifecycle(candidate_id, for_update=True)
        rev = self._session.scalar(
            select(AICandidateRevocationEntity).where(
                AICandidateRevocationEntity.candidate_id == candidate_id,
                AICandidateRevocationEntity.revocation_key == revocation_key,
            )
        )
        if rev is None:
            raise AICandidateLifecycleError("NOT_FOUND", "revocation missing")

        if rev.revocation_status == "COMPLETED":
            return {
                "idempotent_replay": True,
                "revocation": self._public_revocation(rev),
                "lifecycle": self._public(row),
            }

        if rev.revocation_status == "BLOCKED":
            raise AICandidateLifecycleError(
                "REVOCATION_BLOCKED",
                "revocation blocked by references",
            )

        blocker_result = check_revocation_blockers(
            self._session, candidate_id=candidate_id
        )
        if blocker_result["blocked"]:
            rev.revocation_status = "BLOCKED"
            rev.blocked_reasons = blocker_result["blockers"]
            self._session.flush()
            raise AICandidateLifecycleError(
                "REVOCATION_BLOCKED",
                "blockers detected on approve",
            )

        now = _now()
        rev.revocation_status = "APPROVED"
        rev.approved_by = actor
        rev.approved_at = now

        row.revoked_at = now
        self._transition(
            row,
            new_status="REVOKED",
            actor=actor,
            action="REVOCATION_COMPLETED",
            reason=reason,
            correlation_id=correlation_id,
            expected_version=expected_version,
        )
        rev.revocation_status = "COMPLETED"
        rev.completed_at = now
        row.health_status = compute_health(row)
        self._session.flush()
        return {
            "idempotent_replay": False,
            "revocation": self._public_revocation(rev),
            "lifecycle": self._public(row),
        }

    def cancel_revocation(
        self,
        candidate_id: int,
        *,
        revocation_key: str,
        expected_version: int,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_lifecycle(candidate_id, for_update=True)
        rev = self._session.scalar(
            select(AICandidateRevocationEntity).where(
                AICandidateRevocationEntity.candidate_id == candidate_id,
                AICandidateRevocationEntity.revocation_key == revocation_key,
            )
        )
        if rev is None:
            raise AICandidateLifecycleError("NOT_FOUND", "revocation missing")

        if rev.revocation_status in {"COMPLETED", "CANCELLED"}:
            return {
                "idempotent_replay": True,
                "revocation": self._public_revocation(rev),
                "lifecycle": self._public(row),
            }

        rev.revocation_status = "CANCELLED"
        rev.cancelled_at = _now()

        restore = "PROMOTED" if row.last_validated_at else "PROMOTED"
        if row.lifecycle_status == "REVOCATION_REQUESTED" and can_transition(
            row.lifecycle_status, restore
        ):
            self._transition(
                row,
                new_status=restore,
                actor=actor,
                action="REVOCATION_CANCELLED",
                reason=reason,
                correlation_id=correlation_id,
                expected_version=expected_version,
            )
        else:
            self._bump_version(row, actor)

        self._session.flush()
        return {
            "revocation": self._public_revocation(rev),
            "lifecycle": self._public(row),
        }

    def archive(
        self,
        candidate_id: int,
        *,
        expected_version: int,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._get_lifecycle(candidate_id, for_update=True)
        row.archived_at = _now()
        self._transition(
            row,
            new_status="ARCHIVED",
            actor=actor,
            action="ARCHIVED",
            reason=reason,
            correlation_id=correlation_id,
            expected_version=expected_version,
        )
        self._session.flush()
        return {"lifecycle": self._public(row)}

    def supersede(
        self,
        previous_candidate_id: int,
        replacement_candidate_id: int,
        *,
        expected_version: int,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        validation = validate_supersession_pair(
            self._session,
            previous_candidate_id=previous_candidate_id,
            replacement_candidate_id=replacement_candidate_id,
        )
        if not validation["allowed"]:
            raise AICandidateLifecycleError(
                "SUPERSESSION_BLOCKED",
                ",".join(validation["blockers"]),
            )

        previous = self._get_lifecycle(previous_candidate_id, for_update=True)
        self._check_version(previous, expected_version)

        now = _now()
        supersession = build_supersession_entity(
            previous_candidate_id=previous_candidate_id,
            replacement_candidate_id=replacement_candidate_id,
            requested_by=actor,
            reason=reason,
            correlation_id=correlation_id,
        )
        self._session.add(supersession)

        previous.superseded_at = now
        self._transition(
            previous,
            new_status="SUPERSEDED",
            actor=actor,
            action="SUPERSEDED",
            reason=reason,
            correlation_id=correlation_id,
            expected_version=expected_version,
        )
        previous.health_status = compute_health(previous)

        replacement = self._get_lifecycle(replacement_candidate_id)
        self._session.flush()
        return {
            "previous": self._public(previous),
            "replacement": self._public(replacement),
            "supersession_id": supersession.supersession_id,
        }

    def get_history(
        self,
        candidate_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._get_lifecycle(candidate_id)
        stmt = (
            select(AICandidateLifecycleHistoryEntity)
            .where(AICandidateLifecycleHistoryEntity.candidate_id == candidate_id)
            .order_by(AICandidateLifecycleHistoryEntity.created_at.desc())
        )
        rows = self._session.scalars(stmt.limit(limit).offset(offset)).all()
        return {
            "items": [
                {
                    "history_id": h.history_id,
                    "action": h.action,
                    "previous_lifecycle_status": h.previous_lifecycle_status,
                    "new_lifecycle_status": h.new_lifecycle_status,
                    "previous_health_status": h.previous_health_status,
                    "new_health_status": h.new_health_status,
                    "reason": h.reason,
                    "requested_by": h.requested_by,
                    "correlation_id": h.correlation_id,
                    "created_at": h.created_at.isoformat() if h.created_at else None,
                }
                for h in rows
            ],
            "limit": limit,
            "offset": offset,
        }

    def get_provenance(self, candidate_id: int) -> dict[str, Any]:
        self._get_lifecycle(candidate_id)
        snapshot = self._session.scalar(
            select(AICandidateProvenanceSnapshotEntity).where(
                AICandidateProvenanceSnapshotEntity.candidate_id == candidate_id
            )
        )
        if snapshot is None:
            raise AICandidateLifecycleError("NOT_FOUND", "provenance missing")
        return {
            "candidate_id": candidate_id,
            "promotion_request_id": snapshot.promotion_request_id,
            "promotion_link_id": snapshot.promotion_link_id,
            "queue_id": snapshot.queue_id,
            "source_type": snapshot.source_type,
            "source_id": snapshot.source_id,
            "source_result_hash": snapshot.source_result_hash,
            "evidence_bundle_hash": snapshot.evidence_bundle_hash,
            "queue_version_snapshot": snapshot.queue_version_snapshot,
            "candidate_result_hash": snapshot.candidate_result_hash,
            "combined_source_fingerprint": snapshot.combined_source_fingerprint,
            "schema_version": snapshot.schema_version,
            "source_graph": snapshot.source_graph,
            "created_at": (
                snapshot.created_at.isoformat() if snapshot.created_at else None
            ),
        }

    def get_revalidations(
        self,
        candidate_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._get_lifecycle(candidate_id)
        stmt = (
            select(AICandidateRevalidationEntity)
            .where(AICandidateRevalidationEntity.candidate_id == candidate_id)
            .order_by(AICandidateRevalidationEntity.created_at.desc())
        )
        rows = self._session.scalars(stmt.limit(limit).offset(offset)).all()
        return {
            "items": [self._public_revalidation(r) for r in rows],
            "limit": limit,
            "offset": offset,
        }

    def get_revocations(
        self,
        candidate_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._get_lifecycle(candidate_id)
        stmt = (
            select(AICandidateRevocationEntity)
            .where(AICandidateRevocationEntity.candidate_id == candidate_id)
            .order_by(AICandidateRevocationEntity.created_at.desc())
        )
        rows = self._session.scalars(stmt.limit(limit).offset(offset)).all()
        return {
            "items": [self._public_revocation(r) for r in rows],
            "limit": limit,
            "offset": offset,
        }

    def dashboard_summary(self) -> dict[str, Any]:
        counts_by_lifecycle = dict(
            self._session.execute(
                select(
                    AICandidateLifecycleEntity.lifecycle_status,
                    func.count(),
                ).group_by(AICandidateLifecycleEntity.lifecycle_status)
            ).all()
        )
        counts_by_health = dict(
            self._session.execute(
                select(
                    AICandidateLifecycleEntity.health_status,
                    func.count(),
                ).group_by(AICandidateLifecycleEntity.health_status)
            ).all()
        )
        lifecycle_counts = {k: int(v) for k, v in counts_by_lifecycle.items()}
        health_counts = {k: int(v) for k, v in counts_by_health.items()}

        total = self._session.scalar(
            select(func.count()).select_from(AICandidateLifecycleEntity)
        )
        pending_revalidation = self._session.scalar(
            select(func.count()).where(
                AICandidateLifecycleEntity.revalidation_required.is_(True)
            )
        )
        source_changed_count = self._session.scalar(
            select(func.count()).where(
                AICandidateLifecycleEntity.source_changed.is_(True)
            )
        )
        active_revocations = self._session.scalar(
            select(func.count()).where(
                AICandidateRevocationEntity.revocation_status.in_(
                    ACTIVE_REVOCATION_STATUSES
                )
            )
        )

        now = _now()
        expiring_threshold = now + timedelta(hours=24)
        non_terminal = TERMINAL_LIFECYCLE_STATUSES | {"EXPIRED"}
        expiring_soon = self._session.scalar(
            select(func.count()).where(
                AICandidateLifecycleEntity.expiration_at.is_not(None),
                AICandidateLifecycleEntity.expiration_at <= expiring_threshold,
                AICandidateLifecycleEntity.expiration_at > now,
                AICandidateLifecycleEntity.lifecycle_status.notin_(non_terminal),
            )
        )

        return {
            "total": int(total or 0),
            "healthy": int(health_counts.get("HEALTHY") or 0),
            "warning": int(health_counts.get("WARNING") or 0),
            "stale": int(health_counts.get("STALE") or 0),
            "revalidation_required": int(pending_revalidation or 0),
            "expired": int(lifecycle_counts.get("EXPIRED") or 0),
            "revoked": int(lifecycle_counts.get("REVOKED") or 0),
            "superseded": int(lifecycle_counts.get("SUPERSEDED") or 0),
            "archived": int(lifecycle_counts.get("ARCHIVED") or 0),
            "source_changed": int(source_changed_count or 0),
            "expiring_soon": int(expiring_soon or 0),
            "revocation_blocked": int(
                lifecycle_counts.get("REVOCATION_BLOCKED") or 0
            ),
            "lifecycle_counts": lifecycle_counts,
            "health_counts": health_counts,
            "revalidation_required_count": int(pending_revalidation or 0),
            "active_revocation_count": int(active_revocations or 0),
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    @staticmethod
    def _public_revalidation(row: AICandidateRevalidationEntity) -> dict[str, Any]:
        return {
            "revalidation_id": row.revalidation_id,
            "candidate_id": row.candidate_id,
            "revalidation_key": row.revalidation_key,
            "revalidation_status": row.revalidation_status,
            "expected_fingerprint": row.expected_fingerprint,
            "actual_fingerprint": row.actual_fingerprint,
            "fingerprint_match": row.fingerprint_match,
            "warnings": row.warnings,
            "requested_by": row.requested_by,
            "completed_by": row.completed_by,
            "reason": row.reason,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _public_revocation(row: AICandidateRevocationEntity) -> dict[str, Any]:
        return {
            "revocation_id": row.revocation_id,
            "candidate_id": row.candidate_id,
            "revocation_key": row.revocation_key,
            "revocation_status": row.revocation_status,
            "blocked_reasons": row.blocked_reasons,
            "requested_by": row.requested_by,
            "approved_by": row.approved_by,
            "reason": row.reason,
            "requested_at": (
                row.requested_at.isoformat() if row.requested_at else None
            ),
            "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
