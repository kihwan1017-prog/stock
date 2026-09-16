"""STEP 11-13 — Provenance snapshot from promotion chain (no raw prompts)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.candidate_assessment.entities import (
    AICandidateAssessmentEntity,
)
from stock_platform.ai.candidate_consensus.entities import AICandidateConsensusEntity
from stock_platform.ai.candidate_lifecycle.constants import PROVENANCE_SCHEMA_VERSION
from stock_platform.ai.candidate_lifecycle.entities import (
    AICandidateProvenanceSnapshotEntity,
)
from stock_platform.ai.candidate_lifecycle.fingerprint import compute_fingerprint
from stock_platform.ai.candidate_promotion.entities import (
    AICandidatePromotionLinkEntity,
    AICandidatePromotionRequestEntity,
)
from stock_platform.ai.candidate_recommendation_queue.entities import (
    AICandidateRecommendationQueueEntity,
)


def _source_node(
    *,
    source_type: str | None,
    source_id: int | None,
    session: Session,
) -> dict[str, Any]:
    """Assessment/Consensus 해시·ID만 수집 (raw prompt 제외)."""
    if not source_type or source_id is None:
        return {}

    if source_type == "CANDIDATE_ASSESSMENT":
        row = session.get(AICandidateAssessmentEntity, source_id)
        if row is None:
            return {"source_type": source_type, "source_id": source_id, "missing": True}
        return {
            "source_type": source_type,
            "source_id": source_id,
            "result_hash": row.result_hash,
            "evidence_bundle_hash": row.evidence_bundle_hash,
            "source_version_hash": row.source_version_hash,
            "input_hash": row.input_hash,
            "assessment_status": row.assessment_status,
        }

    if source_type == "CANDIDATE_CONSENSUS":
        row = session.get(AICandidateConsensusEntity, source_id)
        if row is None:
            return {"source_type": source_type, "source_id": source_id, "missing": True}
        return {
            "source_type": source_type,
            "source_id": source_id,
            "result_hash": row.result_hash,
            "evidence_bundle_hash": row.evidence_bundle_hash,
            "source_version_hash": row.source_version_hash,
            "consensus_status": row.consensus_status,
        }

    return {"source_type": source_type, "source_id": source_id}


def build_source_graph(
    *,
    session: Session,
    promotion_request: AICandidatePromotionRequestEntity,
    promotion_link: AICandidatePromotionLinkEntity,
    queue: AICandidateRecommendationQueueEntity | None,
) -> dict[str, Any]:
    """Promotion → Queue → Assessment/Consensus 해시 그래프."""
    graph: dict[str, Any] = {
        "promotion_request_id": promotion_request.promotion_request_id,
        "promotion_link_id": promotion_link.link_id,
        "queue_id": promotion_link.queue_id,
        "source_type": promotion_request.source_type,
        "source_id": promotion_request.source_id,
        "source_result_hash": promotion_request.source_result_hash,
        "evidence_bundle_hash": promotion_request.evidence_bundle_hash,
        "candidate_result_hash": promotion_link.candidate_result_hash,
        "mapping_version": promotion_request.mapping_version,
        "score_formula_version": promotion_request.score_formula_version,
    }

    if queue is not None:
        graph["queue"] = {
            "queue_id": queue.queue_id,
            "queue_key": queue.queue_key,
            "source_result_hash": queue.source_result_hash,
            "evidence_bundle_hash": queue.evidence_bundle_hash,
            "queue_status": queue.queue_status,
            "candidate_assessment_id": queue.candidate_assessment_id,
            "candidate_consensus_id": queue.candidate_consensus_id,
        }

    graph["source"] = _source_node(
        source_type=promotion_request.source_type,
        source_id=promotion_request.source_id,
        session=session,
    )
    return graph


def build_combined_fingerprint(source_graph: dict[str, Any]) -> str:
    """source_graph 해시/ID 필드만으로 combined fingerprint."""
    fields = {
        "source_result_hash": source_graph.get("source_result_hash"),
        "evidence_bundle_hash": source_graph.get("evidence_bundle_hash"),
        "candidate_result_hash": source_graph.get("candidate_result_hash"),
        "mapping_version": source_graph.get("mapping_version"),
        "score_formula_version": source_graph.get("score_formula_version"),
        "source": source_graph.get("source"),
    }
    queue = source_graph.get("queue")
    if isinstance(queue, dict):
        fields["queue_source_result_hash"] = queue.get("source_result_hash")
        fields["queue_evidence_bundle_hash"] = queue.get("evidence_bundle_hash")
    return compute_fingerprint(fields)


def build_provenance_snapshot(
    *,
    session: Session,
    candidate_id: int,
    promotion_request: AICandidatePromotionRequestEntity,
    promotion_link: AICandidatePromotionLinkEntity,
    queue: AICandidateRecommendationQueueEntity | None = None,
) -> AICandidateProvenanceSnapshotEntity:
    """Provenance snapshot 엔티티 생성 (INSERT는 caller)."""
    source_graph = build_source_graph(
        session=session,
        promotion_request=promotion_request,
        promotion_link=promotion_link,
        queue=queue,
    )
    combined = build_combined_fingerprint(source_graph)
    return AICandidateProvenanceSnapshotEntity(
        candidate_id=candidate_id,
        promotion_request_id=promotion_request.promotion_request_id,
        promotion_link_id=promotion_link.link_id,
        queue_id=promotion_link.queue_id,
        source_type=promotion_request.source_type,
        source_id=promotion_request.source_id,
        source_result_hash=promotion_request.source_result_hash,
        evidence_bundle_hash=promotion_request.evidence_bundle_hash,
        queue_version_snapshot=promotion_request.queue_version_snapshot,
        candidate_result_hash=promotion_link.candidate_result_hash,
        combined_source_fingerprint=combined,
        schema_version=PROVENANCE_SCHEMA_VERSION,
        source_graph=source_graph,
    )
