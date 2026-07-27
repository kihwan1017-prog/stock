"""STEP 11-8 — Review Assignment / Review / Decision Service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.document_analysis.entities import AIDocumentAnalysisEntity
from stock_platform.ai.market_analysis.entities import AIMarketAnalysisEntity
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.ai.review.constants import (
    DECISION,
    FINDING_TYPES,
    QUALITY_DISCLAIMER,
    REVIEWABLE_ANALYSIS_STATUSES,
    SEVERITIES,
    SOURCE_TYPES,
)
from stock_platform.ai.review.decision import calculate_decision
from stock_platform.ai.review.entities import (
    AIAnalysisReviewDecisionEntity,
    AIAnalysisReviewEntity,
    AIAnalysisReviewFindingEntity,
    AIReviewAssignmentEntity,
)
from stock_platform.ai.review.rubric import compute_overall_score, validate_optional_score


class AIReviewError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AIReviewService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _resolve_source(
        self, source_type: str, source_id: int
    ) -> dict[str, Any]:
        if source_type not in SOURCE_TYPES:
            raise AIReviewError("INVALID_SOURCE_TYPE", "bad source type")
        if source_type in {"NEWS", "DISCLOSURE"}:
            row = self._session.get(AIDocumentAnalysisEntity, source_id)
            if row is None:
                raise AIReviewError("SOURCE_NOT_FOUND", "document analysis missing")
            return {
                "status": row.analysis_status,
                "document_analysis_id": row.document_analysis_id,
                "market_analysis_id": None,
                "execution_result_id": row.execution_result_id,
                "task_type": row.task_type,
                "safe_result": row.safe_result,
                "superseded": row.analysis_status == "SUPERSEDED",
            }
        if source_type in {"CHART", "MARKET"}:
            row = self._session.get(AIMarketAnalysisEntity, source_id)
            if row is None:
                raise AIReviewError("SOURCE_NOT_FOUND", "market analysis missing")
            return {
                "status": row.analysis_status,
                "document_analysis_id": None,
                "market_analysis_id": row.market_analysis_id,
                "execution_result_id": row.execution_result_id,
                "task_type": row.task_type,
                "safe_result": row.safe_result,
                "superseded": row.analysis_status == "SUPERSEDED",
            }
        if source_type == "CANDIDATE_ASSESSMENT":
            from stock_platform.ai.candidate_assessment.entities import (
                AICandidateAssessmentEntity,
            )

            row = self._session.get(AICandidateAssessmentEntity, source_id)
            if row is None:
                raise AIReviewError(
                    "SOURCE_NOT_FOUND", "candidate assessment missing"
                )
            raw_status = row.assessment_status
            if raw_status in {
                "VALIDATED",
                "VALIDATED_WITH_WARNINGS",
            }:
                mapped_status = raw_status
            elif raw_status.startswith("REVIEW_"):
                mapped_status = "VALIDATED_ANALYSIS"
            else:
                mapped_status = raw_status
            return {
                "status": mapped_status,
                "document_analysis_id": None,
                "market_analysis_id": None,
                "execution_result_id": row.execution_result_id,
                "task_type": row.task_type,
                "safe_result": row.safe_result,
                "superseded": raw_status == "SUPERSEDED",
            }
        if source_type == "CANDIDATE_CONSENSUS":
            from stock_platform.ai.candidate_consensus.entities import (
                AICandidateConsensusEntity,
            )

            row = self._session.get(AICandidateConsensusEntity, source_id)
            if row is None:
                raise AIReviewError(
                    "SOURCE_NOT_FOUND", "candidate consensus missing"
                )
            raw_status = row.consensus_status
            if raw_status in {
                "VALIDATED",
                "VALIDATED_WITH_WARNINGS",
                "CALCULATED",
            }:
                mapped_status = raw_status
            elif raw_status.startswith("REVIEW_"):
                mapped_status = "VALIDATED_ANALYSIS"
            else:
                mapped_status = raw_status
            return {
                "status": mapped_status,
                "document_analysis_id": None,
                "market_analysis_id": None,
                "execution_result_id": row.execution_request_id,
                "task_type": row.task_type,
                "safe_result": row.safe_result,
                "superseded": raw_status == "SUPERSEDED",
            }
        # EXECUTION — 최소 메타만
        return {
            "status": "VALIDATED_ANALYSIS",
            "document_analysis_id": None,
            "market_analysis_id": None,
            "execution_result_id": source_id,
            "task_type": "SUMMARIZE",
            "safe_result": None,
            "superseded": False,
        }

    def _public_assignment(
        self, row: AIReviewAssignmentEntity
    ) -> dict[str, Any]:
        return {
            "id": row.assignment_id,
            "analysis_source_type": row.analysis_source_type,
            "source_analysis_id": row.source_analysis_id,
            "document_analysis_id": row.document_analysis_id,
            "market_analysis_id": row.market_analysis_id,
            "execution_result_id": row.execution_result_id,
            "assigned_reviewer_id": row.assigned_reviewer_id,
            "assigned_by": row.assigned_by,
            "status": row.status,
            "priority": row.priority,
            "due_at": row.due_at.isoformat() if row.due_at else None,
            "assigned_at": row.assigned_at.isoformat() if row.assigned_at else None,
            "lock_version": row.lock_version,
            "reason": row.reason,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "disclaimer": QUALITY_DISCLAIMER,
        }

    def _public_review(self, row: AIAnalysisReviewEntity) -> dict[str, Any]:
        return {
            "id": row.review_id,
            "assignment_id": row.assignment_id,
            "reviewer_id": row.reviewer_id,
            "review_version": row.review_version,
            "status": row.status,
            "decision": row.decision,
            "overall_score": row.overall_score,
            "correctness_score": row.correctness_score,
            "relevance_score": row.relevance_score,
            "completeness_score": row.completeness_score,
            "citation_score": row.citation_score,
            "safety_score": row.safety_score,
            "clarity_score": row.clarity_score,
            "calibration_score": row.calibration_score,
            "data_quality_score": row.data_quality_score,
            "reviewer_confidence": row.reviewer_confidence,
            "findings_summary": row.findings_summary,
            "correction_summary": row.correction_summary,
            "revision_request": row.revision_request,
            "reason": row.reason,
            "submitted_at": (
                row.submitted_at.isoformat() if row.submitted_at else None
            ),
            "disclaimer": QUALITY_DISCLAIMER,
        }

    def create_assignment(
        self,
        *,
        actor: str,
        reason: str,
        analysis_source_type: str,
        source_analysis_id: int,
        assigned_reviewer_id: str | None = None,
        priority: str = "NORMAL",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        src = self._resolve_source(analysis_source_type, source_analysis_id)
        if src["status"] not in REVIEWABLE_ANALYSIS_STATUSES:
            raise AIReviewError(
                "NOT_REVIEWABLE",
                f"status {src['status']} not reviewable",
            )
        # Safe Result 없는 VALIDATED만 본심사; BLOCKED/INVALID는 Failure Review 허용
        if src["status"] in {
            "VALIDATED_ANALYSIS",
            "VALIDATED_WITH_WARNINGS",
            "SUPERSEDED",
        }:
            if src.get("safe_result") is None and analysis_source_type != "EXECUTION":
                raise AIReviewError("NO_SAFE_RESULT", "Safe Result required")

        if assigned_reviewer_id:
            existing = self._session.scalar(
                select(AIReviewAssignmentEntity).where(
                    AIReviewAssignmentEntity.analysis_source_type
                    == analysis_source_type,
                    AIReviewAssignmentEntity.source_analysis_id
                    == source_analysis_id,
                    AIReviewAssignmentEntity.assigned_reviewer_id
                    == assigned_reviewer_id,
                    AIReviewAssignmentEntity.status.notin_(
                        ["CANCELLED", "EXPIRED"]
                    ),
                )
            )
            if existing is not None:
                return {
                    "idempotent_replay": True,
                    "assignment": self._public_assignment(existing),
                }

        row = AIReviewAssignmentEntity(
            analysis_source_type=analysis_source_type,
            source_analysis_id=source_analysis_id,
            document_analysis_id=src.get("document_analysis_id"),
            market_analysis_id=src.get("market_analysis_id"),
            execution_result_id=src.get("execution_result_id"),
            assigned_reviewer_id=assigned_reviewer_id,
            assigned_by=actor,
            status="ASSIGNED" if assigned_reviewer_id else "UNASSIGNED",
            priority=priority,
            assigned_at=_now() if assigned_reviewer_id else None,
            reason=reason[:500],
            correlation_id=idempotency_key,
        )
        self._session.add(row)
        self._session.flush()
        self._ensure_decision(analysis_source_type, source_analysis_id)
        self._session.commit()
        self._session.refresh(row)
        return {
            "idempotent_replay": False,
            "assignment": self._public_assignment(row),
            "source_superseded": src.get("superseded"),
            "disclaimer": QUALITY_DISCLAIMER,
        }

    def assign(
        self,
        assignment_id: int,
        *,
        actor: str,
        reviewer_id: str,
        reason: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        row = self._session.get(AIReviewAssignmentEntity, assignment_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "assignment not found")
        if expected_version is not None and row.lock_version != expected_version:
            raise AIReviewError("VERSION_CONFLICT", "optimistic lock")
        if row.status in {"CANCELLED", "COMPLETED", "EXPIRED"}:
            raise AIReviewError("INVALID_STATE", "cannot assign")
        # 동일 reviewer 중복 assignment 방지
        dup = self._session.scalar(
            select(AIReviewAssignmentEntity).where(
                AIReviewAssignmentEntity.analysis_source_type
                == row.analysis_source_type,
                AIReviewAssignmentEntity.source_analysis_id
                == row.source_analysis_id,
                AIReviewAssignmentEntity.assigned_reviewer_id == reviewer_id,
                AIReviewAssignmentEntity.assignment_id != assignment_id,
                AIReviewAssignmentEntity.status.notin_(
                    ["CANCELLED", "EXPIRED"]
                ),
            )
        )
        if dup is not None:
            raise AIReviewError("DUPLICATE_REVIEWER", "reviewer already assigned")
        row.assigned_reviewer_id = reviewer_id
        row.assigned_by = actor
        row.status = "ASSIGNED"
        row.assigned_at = _now()
        row.reason = reason[:500]
        row.lock_version += 1
        self._session.commit()
        return {"assignment": self._public_assignment(row)}

    def reassign(
        self,
        assignment_id: int,
        *,
        actor: str,
        reviewer_id: str,
        reason: str,
    ) -> dict[str, Any]:
        return self.assign(
            assignment_id,
            actor=actor,
            reviewer_id=reviewer_id,
            reason=reason,
        )

    def cancel_assignment(
        self, assignment_id: int, *, actor: str, reason: str
    ) -> dict[str, Any]:
        row = self._session.get(AIReviewAssignmentEntity, assignment_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "assignment not found")
        row.status = "CANCELLED"
        row.reason = reason[:500]
        row.lock_version += 1
        self._session.commit()
        return {"assignment": self._public_assignment(row)}

    def list_assignments(
        self, *, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        stmt = select(AIReviewAssignmentEntity).order_by(
            AIReviewAssignmentEntity.assignment_id.desc()
        )
        if status:
            stmt = stmt.where(AIReviewAssignmentEntity.status == status)
        rows = self._session.scalars(stmt.limit(min(limit, 200))).all()
        return [self._public_assignment(r) for r in rows]

    def get_assignment(self, assignment_id: int) -> dict[str, Any]:
        row = self._session.get(AIReviewAssignmentEntity, assignment_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "assignment not found")
        return self._public_assignment(row)

    def create_review_draft(
        self,
        assignment_id: int,
        *,
        reviewer_id: str,
        reason: str,
        correctness_score: float,
        relevance_score: float,
        completeness_score: float,
        citation_score: float,
        safety_score: float,
        clarity_score: float,
        decision: str,
        calibration_score: float | None = None,
        data_quality_score: float | None = None,
        reviewer_confidence: float | None = None,
        findings_summary: str | None = None,
        correction_summary: str | None = None,
        revision_request: str | None = None,
        findings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        assignment = self._session.get(AIReviewAssignmentEntity, assignment_id)
        if assignment is None:
            raise AIReviewError("NOT_FOUND", "assignment not found")
        if assignment.status in {"CANCELLED", "EXPIRED"}:
            raise AIReviewError("INVALID_STATE", "assignment closed")
        if (
            assignment.assigned_reviewer_id
            and assignment.assigned_reviewer_id != reviewer_id
        ):
            raise AIReviewError(
                "FORBIDDEN", "cannot review others assignment"
            )
        if decision not in DECISION:
            raise AIReviewError("INVALID_DECISION", "bad decision")

        overall = compute_overall_score(
            correctness_score=correctness_score,
            relevance_score=relevance_score,
            completeness_score=completeness_score,
            citation_score=citation_score,
            safety_score=safety_score,
            clarity_score=clarity_score,
        )
        # 기존 draft 있으면 갱신, 아니면 새 version
        latest = self._session.scalar(
            select(AIAnalysisReviewEntity)
            .where(
                AIAnalysisReviewEntity.assignment_id == assignment_id,
                AIAnalysisReviewEntity.reviewer_id == reviewer_id,
            )
            .order_by(AIAnalysisReviewEntity.review_version.desc())
            .limit(1)
        )
        if latest and latest.status == "DRAFT":
            row = latest
        else:
            version = (latest.review_version + 1) if latest else 1
            # SUBMITTED 직접 수정 금지 — draft만 생성
            if latest and latest.status == "SUBMITTED":
                raise AIReviewError(
                    "USE_AMEND",
                    "submitted review cannot be edited; use amend",
                )
            row = AIAnalysisReviewEntity(
                assignment_id=assignment_id,
                reviewer_id=reviewer_id,
                review_version=version,
                status="DRAFT",
            )
            self._session.add(row)

        row.decision = decision
        row.correctness_score = correctness_score
        row.relevance_score = relevance_score
        row.completeness_score = completeness_score
        row.citation_score = citation_score
        row.safety_score = safety_score
        row.clarity_score = clarity_score
        row.overall_score = overall
        row.calibration_score = validate_optional_score(calibration_score)
        row.data_quality_score = validate_optional_score(data_quality_score)
        row.reviewer_confidence = validate_optional_score(reviewer_confidence)
        row.findings_summary = (findings_summary or "")[:2000] or None
        row.correction_summary = (correction_summary or "")[:2000] or None
        row.revision_request = (revision_request or "")[:2000] or None
        row.reason = reason[:500]
        assignment.status = "IN_REVIEW"
        assignment.started_at = assignment.started_at or _now()
        self._session.flush()

        # findings 교체 (draft)
        existing_findings = self._session.scalars(
            select(AIAnalysisReviewFindingEntity).where(
                AIAnalysisReviewFindingEntity.review_id == row.review_id
            )
        ).all()
        for f in existing_findings:
            self._session.delete(f)
        self._add_findings(row.review_id, findings or [])
        self._session.commit()
        self._session.refresh(row)
        return {"review": self._public_review(row)}

    def _add_findings(
        self, review_id: int, findings: list[dict[str, Any]]
    ) -> None:
        for item in findings[:50]:
            ftype = str(item.get("finding_type") or "OTHER")
            sev = str(item.get("severity") or "LOW")
            if ftype not in FINDING_TYPES:
                ftype = "OTHER"
            if sev not in SEVERITIES:
                sev = "LOW"
            desc = str(item.get("description_sanitized") or item.get("description") or "")
            desc = str(sanitize_for_log({"d": desc}).get("d") or "")[:1000]
            if not desc:
                continue
            self._session.add(
                AIAnalysisReviewFindingEntity(
                    review_id=review_id,
                    finding_type=ftype,
                    severity=sev,
                    field_path=(str(item.get("field_path") or "")[:200] or None),
                    finding_code=(str(item.get("finding_code") or "")[:80] or None),
                    description_sanitized=desc,
                    suggested_correction=(
                        str(item.get("suggested_correction") or "")[:1000] or None
                    ),
                    evidence_reference=(
                        str(item.get("evidence_reference") or "")[:200] or None
                    ),
                )
            )

    def submit_review(
        self, review_id: int, *, reviewer_id: str, reason: str
    ) -> dict[str, Any]:
        row = self._session.get(AIAnalysisReviewEntity, review_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "review not found")
        if row.reviewer_id != reviewer_id:
            raise AIReviewError("FORBIDDEN", "not your review")
        if row.status != "DRAFT":
            raise AIReviewError("INVALID_STATE", "only DRAFT can submit")
        if row.overall_score is None:
            raise AIReviewError("INCOMPLETE", "scores required")
        # Critical safety
        critical = self._critical_count(review_id)
        if critical > 0 and row.decision in {
            "APPROVED",
            "APPROVED_WITH_WARNINGS",
        }:
            raise AIReviewError(
                "CRITICAL_SAFETY",
                "cannot approve with critical safety findings",
            )
        row.status = "SUBMITTED"
        row.submitted_at = _now()
        row.reason = reason[:500]
        assignment = self._session.get(
            AIReviewAssignmentEntity, row.assignment_id
        )
        if assignment:
            assignment.status = "COMPLETED"
            assignment.completed_at = _now()
            self._recalculate_decision(
                assignment.analysis_source_type,
                assignment.source_analysis_id,
            )
        self._session.commit()
        self._session.refresh(row)
        return {
            "review": self._public_review(row),
            "disclaimer": QUALITY_DISCLAIMER,
        }

    def amend_review(
        self,
        review_id: int,
        *,
        reviewer_id: str,
        amendment_reason: str,
        correctness_score: float,
        relevance_score: float,
        completeness_score: float,
        citation_score: float,
        safety_score: float,
        clarity_score: float,
        decision: str,
        findings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        old = self._session.get(AIAnalysisReviewEntity, review_id)
        if old is None:
            raise AIReviewError("NOT_FOUND", "review not found")
        if old.reviewer_id != reviewer_id:
            raise AIReviewError("FORBIDDEN", "not your review")
        if old.status not in {"SUBMITTED", "AMENDED"}:
            raise AIReviewError("INVALID_STATE", "amend only submitted")
        if not amendment_reason.strip():
            raise AIReviewError("REASON_REQUIRED", "amendment_reason required")

        overall = compute_overall_score(
            correctness_score=correctness_score,
            relevance_score=relevance_score,
            completeness_score=completeness_score,
            citation_score=citation_score,
            safety_score=safety_score,
            clarity_score=clarity_score,
        )
        new = AIAnalysisReviewEntity(
            assignment_id=old.assignment_id,
            reviewer_id=reviewer_id,
            review_version=old.review_version + 1,
            status="AMENDED",
            decision=decision,
            correctness_score=correctness_score,
            relevance_score=relevance_score,
            completeness_score=completeness_score,
            citation_score=citation_score,
            safety_score=safety_score,
            clarity_score=clarity_score,
            overall_score=overall,
            reason=old.reason,
            amendment_reason=amendment_reason[:500],
            amended_at=_now(),
            submitted_at=_now(),
        )
        self._session.add(new)
        self._session.flush()
        self._add_findings(new.review_id, findings or [])
        assignment = self._session.get(
            AIReviewAssignmentEntity, old.assignment_id
        )
        if assignment:
            self._recalculate_decision(
                assignment.analysis_source_type,
                assignment.source_analysis_id,
            )
        self._session.commit()
        self._session.refresh(new)
        return {"review": self._public_review(new)}

    def withdraw_review(
        self, review_id: int, *, reviewer_id: str, reason: str
    ) -> dict[str, Any]:
        row = self._session.get(AIAnalysisReviewEntity, review_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "review not found")
        if row.reviewer_id != reviewer_id:
            raise AIReviewError("FORBIDDEN", "not your review")
        if row.status not in {"SUBMITTED", "AMENDED", "DRAFT"}:
            raise AIReviewError("INVALID_STATE", "cannot withdraw")
        row.status = "WITHDRAWN"
        row.reason = reason[:500]
        assignment = self._session.get(
            AIReviewAssignmentEntity, row.assignment_id
        )
        if assignment:
            self._recalculate_decision(
                assignment.analysis_source_type,
                assignment.source_analysis_id,
            )
        self._session.commit()
        return {"review": self._public_review(row)}

    def _critical_count(self, review_id: int) -> int:
        rows = self._session.scalars(
            select(AIAnalysisReviewFindingEntity).where(
                AIAnalysisReviewFindingEntity.review_id == review_id,
                AIAnalysisReviewFindingEntity.severity == "CRITICAL",
            )
        ).all()
        # SAFETY_VIOLATION / HALLUCINATION also treated critical-ish
        extra = self._session.scalars(
            select(AIAnalysisReviewFindingEntity).where(
                AIAnalysisReviewFindingEntity.review_id == review_id,
                AIAnalysisReviewFindingEntity.finding_type.in_(
                    ["SAFETY_VIOLATION", "HALLUCINATION"]
                ),
                AIAnalysisReviewFindingEntity.severity.in_(
                    ["HIGH", "CRITICAL"]
                ),
            )
        ).all()
        return len(rows) + len(
            [e for e in extra if e.severity != "CRITICAL"]
        )

    def _ensure_decision(self, source_type: str, source_id: int) -> None:
        existing = self._session.scalar(
            select(AIAnalysisReviewDecisionEntity).where(
                AIAnalysisReviewDecisionEntity.analysis_source_type
                == source_type,
                AIAnalysisReviewDecisionEntity.source_analysis_id == source_id,
            )
        )
        if existing is None:
            self._session.add(
                AIAnalysisReviewDecisionEntity(
                    analysis_source_type=source_type,
                    source_analysis_id=source_id,
                    decision="PENDING",
                )
            )

    def _recalculate_decision(self, source_type: str, source_id: int) -> dict[str, Any]:
        self._ensure_decision(source_type, source_id)
        decision_row = self._session.scalar(
            select(AIAnalysisReviewDecisionEntity).where(
                AIAnalysisReviewDecisionEntity.analysis_source_type
                == source_type,
                AIAnalysisReviewDecisionEntity.source_analysis_id == source_id,
            )
        )
        assert decision_row is not None

        assignments = self._session.scalars(
            select(AIReviewAssignmentEntity).where(
                AIReviewAssignmentEntity.analysis_source_type == source_type,
                AIReviewAssignmentEntity.source_analysis_id == source_id,
                AIReviewAssignmentEntity.status != "CANCELLED",
            )
        ).all()
        reviews: list[AIAnalysisReviewEntity] = []
        for a in assignments:
            latest = self._session.scalar(
                select(AIAnalysisReviewEntity)
                .where(
                    AIAnalysisReviewEntity.assignment_id == a.assignment_id,
                    AIAnalysisReviewEntity.status.in_(
                        ["SUBMITTED", "AMENDED"]
                    ),
                )
                .order_by(AIAnalysisReviewEntity.review_version.desc())
                .limit(1)
            )
            if latest:
                reviews.append(latest)

        critical = 0
        for r in reviews:
            critical += self._critical_count(r.review_id)

        calc = calculate_decision(
            submitted_reviews=[
                {
                    "decision": r.decision,
                    "overall_score": r.overall_score,
                    "safety_score": r.safety_score,
                }
                for r in reviews
            ],
            critical_finding_count=critical,
        )
        decision_row.decision = calc["decision"]
        decision_row.decision_rule = calc["decision_rule"]
        decision_row.consensus_status = calc["consensus_status"]
        decision_row.reviewer_count = calc["reviewer_count"]
        decision_row.approved_count = calc["approved_count"]
        decision_row.rejected_count = calc["rejected_count"]
        decision_row.warning_count = calc["warning_count"]
        decision_row.average_overall_score = calc["average_overall_score"]
        decision_row.critical_finding_count = calc["critical_finding_count"]
        decision_row.decided_at = _now()
        decision_row.lock_version += 1
        return self._public_decision(decision_row)

    def _public_decision(
        self, row: AIAnalysisReviewDecisionEntity
    ) -> dict[str, Any]:
        return {
            "id": row.decision_id,
            "analysis_source_type": row.analysis_source_type,
            "source_analysis_id": row.source_analysis_id,
            "decision": row.decision,
            "decision_rule": row.decision_rule,
            "consensus_status": row.consensus_status,
            "reviewer_count": row.reviewer_count,
            "approved_count": row.approved_count,
            "rejected_count": row.rejected_count,
            "warning_count": row.warning_count,
            "average_overall_score": row.average_overall_score,
            "critical_finding_count": row.critical_finding_count,
            "decided_by": row.decided_by,
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            "override_reason": row.override_reason,
            "lock_version": row.lock_version,
            "label": "AI 분석 품질 승인"
            if row.decision in {"APPROVED", "APPROVED_WITH_WARNINGS"}
            else row.decision,
            "disclaimer": QUALITY_DISCLAIMER,
        }

    def get_decision(
        self, source_type: str, source_id: int
    ) -> dict[str, Any]:
        row = self._session.scalar(
            select(AIAnalysisReviewDecisionEntity).where(
                AIAnalysisReviewDecisionEntity.analysis_source_type
                == source_type,
                AIAnalysisReviewDecisionEntity.source_analysis_id == source_id,
            )
        )
        if row is None:
            self._ensure_decision(source_type, source_id)
            self._session.commit()
            return self.get_decision(source_type, source_id)
        return self._public_decision(row)

    def recalculate_decision(
        self, source_type: str, source_id: int, *, actor: str
    ) -> dict[str, Any]:
        result = self._recalculate_decision(source_type, source_id)
        self._session.commit()
        return result

    def override_decision(
        self,
        source_type: str,
        source_id: int,
        *,
        actor: str,
        decision: str,
        reason: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        if decision not in DECISION:
            raise AIReviewError("INVALID_DECISION", "bad decision")
        if not reason.strip():
            raise AIReviewError("REASON_REQUIRED", "override reason required")
        row = self._session.scalar(
            select(AIAnalysisReviewDecisionEntity).where(
                AIAnalysisReviewDecisionEntity.analysis_source_type
                == source_type,
                AIAnalysisReviewDecisionEntity.source_analysis_id == source_id,
            )
        )
        if row is None:
            self._ensure_decision(source_type, source_id)
            self._session.flush()
            row = self._session.scalar(
                select(AIAnalysisReviewDecisionEntity).where(
                    AIAnalysisReviewDecisionEntity.analysis_source_type
                    == source_type,
                    AIAnalysisReviewDecisionEntity.source_analysis_id
                    == source_id,
                )
            )
        assert row is not None
        if expected_version is not None and row.lock_version != expected_version:
            raise AIReviewError("VERSION_CONFLICT", "optimistic lock")
        # Core Safety: critical findings block APPROVED override
        if (
            decision in {"APPROVED", "APPROVED_WITH_WARNINGS"}
            and row.critical_finding_count > 0
        ):
            raise AIReviewError(
                "CRITICAL_SAFETY",
                "cannot override-approve with critical findings",
            )
        row.decision = decision
        row.decision_rule = "MANAGER_OVERRIDE"
        row.decided_by = actor
        row.decided_at = _now()
        row.override_reason = reason[:500]
        row.lock_version += 1
        self._session.commit()
        return self._public_decision(row)

    def list_reviews(self, assignment_id: int) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(AIAnalysisReviewEntity)
            .where(AIAnalysisReviewEntity.assignment_id == assignment_id)
            .order_by(AIAnalysisReviewEntity.review_version.desc())
        ).all()
        return [self._public_review(r) for r in rows]

    def get_review(self, review_id: int) -> dict[str, Any]:
        row = self._session.get(AIAnalysisReviewEntity, review_id)
        if row is None:
            raise AIReviewError("NOT_FOUND", "review not found")
        findings = self._session.scalars(
            select(AIAnalysisReviewFindingEntity).where(
                AIAnalysisReviewFindingEntity.review_id == review_id
            )
        ).all()
        return {
            **self._public_review(row),
            "findings": [
                {
                    "id": f.finding_id,
                    "finding_type": f.finding_type,
                    "severity": f.severity,
                    "description_sanitized": f.description_sanitized,
                    "field_path": f.field_path,
                }
                for f in findings
            ],
        }

    def dashboard_summary(self) -> dict[str, Any]:
        assignments = self._session.scalars(
            select(AIReviewAssignmentEntity).limit(500)
        ).all()
        decisions = self._session.scalars(
            select(AIAnalysisReviewDecisionEntity).limit(500)
        ).all()
        today = _now().date()
        by_a: dict[str, int] = {}
        for a in assignments:
            by_a[a.status] = by_a.get(a.status, 0) + 1
        by_d: dict[str, int] = {}
        for d in decisions:
            by_d[d.decision] = by_d.get(d.decision, 0) + 1
        completed_today = sum(
            1
            for a in assignments
            if a.completed_at and a.completed_at.date() == today
        )
        scores = [
            float(d.average_overall_score)
            for d in decisions
            if d.average_overall_score is not None
        ]
        return {
            "review_pending": by_a.get("UNASSIGNED", 0) + by_a.get("ASSIGNED", 0),
            "assigned": by_a.get("ASSIGNED", 0),
            "in_review": by_a.get("IN_REVIEW", 0),
            "completed_today": completed_today,
            "approved": by_d.get("APPROVED", 0),
            "approved_with_warnings": by_d.get("APPROVED_WITH_WARNINGS", 0),
            "revision_requested": by_d.get("REVISION_REQUESTED", 0),
            "rejected": by_d.get("REJECTED", 0),
            "major_disagreement": sum(
                1
                for d in decisions
                if d.consensus_status
                in {"MAJOR_DISAGREEMENT", "MANAGER_REVIEW_REQUIRED"}
            ),
            "average_quality_score": (
                round(sum(scores) / len(scores), 4) if scores else None
            ),
            "disclaimer": QUALITY_DISCLAIMER,
            "external_ai_called": False,
            "trading_signal_on_approve": False,
        }
