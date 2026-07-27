"""STEP 11-10 — Admin AI Candidate Consensus API (참고용 초안, 매매 후보 아님)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_consensus.batch_service import (
    AIConsensusBatchService,
)
from stock_platform.ai.candidate_consensus.service import (
    AIConsensusError,
    AIConsensusService,
)
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/ai/candidate-consensuses",
    tags=["Admin AI Candidate Consensuses"],
    dependencies=[Depends(require_admin)],
)


class CreateBody(BaseModel):
    market_type: str
    exchange_code: str
    symbol: str
    instrument_id: int | None = None
    assessment_ids: list[int] = Field(min_length=1)
    calculation_mode: str = "DETERMINISTIC_ONLY"
    synthesis_execution_mode: str = "MOCK"
    synthesis_provider_code: str | None = "mock"
    synthesis_model: str | None = None
    prompt_version_id: int | None = None
    max_tokens: int = 768
    timeout_sec: float = 45.0
    fallback_enabled: bool = False
    require_reviewed_members: bool = False
    minimum_provider_families: int = 1
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)
    force_new_version: bool = False
    correlation_id: str | None = None


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    confirm: bool = False


class RecalculateBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)


class RequestReviewBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    assigned_reviewer_id: str | None = None


class BatchBody(BaseModel):
    market_type: str
    exchange_code: str
    instruments: list[dict[str, Any]]
    calculation_mode: str = "DETERMINISTIC_ONLY"
    synthesis_execution_mode: str = "MOCK"
    synthesis_provider_code: str = "mock"
    synthesis_model: str | None = None
    prompt_version_id: int | None = None
    require_reviewed_members: bool = False
    minimum_provider_families: int = 1
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)
    confirm: bool = False
    estimated_max_tokens: int | None = None
    estimated_max_cost: float | None = None


class CompareBody(BaseModel):
    left_id: int
    right_id: int


def _audit(session: Session, *, event_type: str, actor: str, detail: dict) -> None:
    try:
        AuditLogService(session).record(
            event_type=event_type,
            actor=actor,
            detail=sanitize_for_log(detail),
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


def _raise(exc: AIConsensusError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    if exc.code in {
        "CONFIRM_REQUIRED",
        "NOT_ELIGIBLE",
        "INSUFFICIENT_MEMBERS",
        "PROVIDER_DIVERSITY",
    }:
        code = status.HTTP_403_FORBIDDEN
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


@router.get("")
def list_consensuses(
    market_type: str | None = None,
    consensus_type: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIConsensusService(session).list(
        market_type=market_type,
        consensus_type=consensus_type,
        limit=limit,
    )
    return {"count": len(items), "items": items}


@router.get("/dashboard")
def dashboard(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AIConsensusService(session).dashboard_summary()


@router.post("")
def create_consensus(
    body: CreateBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIConsensusService(session).create(
            actor=actor,
            reason=body.reason,
            market_type=body.market_type,
            exchange_code=body.exchange_code,
            symbol=body.symbol,
            instrument_id=body.instrument_id,
            assessment_ids=body.assessment_ids,
            calculation_mode=body.calculation_mode,
            synthesis_execution_mode=body.synthesis_execution_mode,
            synthesis_provider_code=body.synthesis_provider_code,
            synthesis_model=body.synthesis_model,
            prompt_version_id=body.prompt_version_id,
            max_tokens=body.max_tokens,
            timeout_sec=body.timeout_sec,
            fallback_enabled=body.fallback_enabled,
            require_reviewed_members=body.require_reviewed_members,
            minimum_provider_families=body.minimum_provider_families,
            idempotency_key=body.idempotency_key,
            force_new_version=body.force_new_version,
            correlation_id=body.correlation_id,
        )
    except AIConsensusError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CONSENSUS_CREATED",
        actor=actor,
        detail={
            "consensus_id": result["consensus"]["id"],
            "market_type": body.market_type,
            "exchange_code": body.exchange_code,
            "symbol": body.symbol,
            "calculation_mode": body.calculation_mode,
            "assessment_count": len(body.assessment_ids),
        },
    )
    return result


@router.post("/batches")
def create_batch(
    body: BatchBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIConsensusBatchService(session).create_batch(
            actor=actor,
            reason=body.reason,
            market_type=body.market_type,
            exchange_code=body.exchange_code,
            instruments=body.instruments,
            calculation_mode=body.calculation_mode,
            synthesis_execution_mode=body.synthesis_execution_mode,
            synthesis_provider_code=body.synthesis_provider_code,
            synthesis_model=body.synthesis_model,
            prompt_version_id=body.prompt_version_id,
            require_reviewed_members=body.require_reviewed_members,
            minimum_provider_families=body.minimum_provider_families,
            confirm=body.confirm,
            idempotency_key=body.idempotency_key,
            estimated_max_tokens=body.estimated_max_tokens,
            estimated_max_cost=body.estimated_max_cost,
        )
    except AIConsensusError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CONSENSUS_CREATED",
        actor=actor,
        detail={
            "created_count": result["created_count"],
            "market_type": body.market_type,
            "exchange_code": body.exchange_code,
            "instrument_count": len(body.instruments),
            "calculation_mode": body.calculation_mode,
            "batch": True,
        },
    )
    return result


@router.post("/compare")
def compare(
    body: CompareBody,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AIConsensusService(session).compare(body.left_id, body.right_id)
    except AIConsensusError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{consensus_id}")
def get_consensus(
    consensus_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return {"consensus": AIConsensusService(session).get(consensus_id)}
    except AIConsensusError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{consensus_id}/members")
def get_members(
    consensus_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        items = AIConsensusService(session).members(consensus_id)
    except AIConsensusError as exc:
        _raise(exc)
    return {"count": len(items), "items": items}


@router.get("/{consensus_id}/weights")
def get_weights(
    consensus_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        weights = AIConsensusService(session).weights(consensus_id)
        items = weights.get("weights") or []
    except AIConsensusError as exc:
        _raise(exc)
    return {"count": len(items), "items": items}


@router.get("/{consensus_id}/conflicts")
def get_conflicts(
    consensus_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        items = AIConsensusService(session).conflicts(consensus_id)
    except AIConsensusError as exc:
        _raise(exc)
    return {"count": len(items), "items": items}


@router.get("/{consensus_id}/history")
def get_history(
    consensus_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        items = AIConsensusService(session).history(consensus_id)
    except AIConsensusError as exc:
        _raise(exc)
    return {"count": len(items), "items": items}


@router.post("/{consensus_id}/dry-run")
def dry_run(
    consensus_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIConsensusService(session).dry_run(
            consensus_id, actor=actor
        )
    except AIConsensusError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CONSENSUS_DRY_RUN_COMPLETED",
        actor=actor,
        detail={"consensus_id": consensus_id, "reason": body.reason},
    )
    return result


@router.post("/{consensus_id}/calculate")
def calculate(
    consensus_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIConsensusService(session).calculate(
            consensus_id, actor=actor, reason=body.reason
        )
    except AIConsensusError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CONSENSUS_CALCULATED",
        actor=actor,
        detail={
            "consensus_id": consensus_id,
            "ok": result.get("ok"),
            "external_ai_called": result.get("external_ai_called", False),
            "reason": body.reason,
        },
    )
    return result


@router.post("/{consensus_id}/synthesize")
async def synthesize(
    consensus_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = await AIConsensusService(session).synthesize(
            consensus_id,
            actor=actor,
            reason=body.reason,
            confirm=body.confirm,
        )
    except AIConsensusError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CONSENSUS_SYNTHESIS_COMPLETED",
        actor=actor,
        detail={
            "consensus_id": consensus_id,
            "ok": result.get("ok"),
            "external_ai_called": result.get("external_ai_called"),
            "reason": body.reason,
        },
    )
    return result


@router.post("/{consensus_id}/cancel")
def cancel(
    consensus_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIConsensusService(session).cancel(
            consensus_id, actor=actor, reason=body.reason
        )
    except AIConsensusError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CONSENSUS_CANCELLED",
        actor=actor,
        detail={"consensus_id": consensus_id, "reason": body.reason},
    )
    return result


@router.post("/{consensus_id}/recalculate")
def recalculate(
    consensus_id: int,
    body: RecalculateBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIConsensusService(session).recalculate(
            consensus_id,
            actor=actor,
            reason=body.reason,
            idempotency_key=body.idempotency_key,
        )
    except AIConsensusError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CONSENSUS_RECALCULATED",
        actor=actor,
        detail={
            "previous_id": consensus_id,
            "new_id": result["consensus"]["id"],
            "reason": body.reason,
        },
    )
    return result


@router.post("/{consensus_id}/resynthesize")
async def resynthesize(
    consensus_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = await AIConsensusService(session).resynthesize(
            consensus_id,
            actor=actor,
            reason=body.reason,
            confirm=body.confirm,
        )
    except AIConsensusError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CONSENSUS_RESYNTHESIZED",
        actor=actor,
        detail={
            "consensus_id": consensus_id,
            "ok": result.get("ok"),
            "external_ai_called": result.get("external_ai_called"),
            "reason": body.reason,
        },
    )
    return result


@router.post("/{consensus_id}/request-review")
def request_review(
    consensus_id: int,
    body: RequestReviewBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIConsensusService(session).request_review(
            consensus_id,
            actor=actor,
            reason=body.reason,
            assigned_reviewer_id=body.assigned_reviewer_id,
        )
    except AIConsensusError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_CONSENSUS_REVIEW_REQUESTED",
        actor=actor,
        detail={"consensus_id": consensus_id, "reason": body.reason},
    )
    return result
