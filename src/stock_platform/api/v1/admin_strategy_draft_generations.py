"""STEP 12-2-2/12-2-3 — Admin Strategy Draft Generation API.

승인(APPROVED)된 Strategy Request와 유효한 Candidate를 근거로 AI가
구조화된 Strategy Draft 초안을 생성하도록 요청하는 관리자 전용 API.
결과물은 검토 전 Strategy Draft일 뿐이며, 자동 승인/Backtest/Paper
Trading/Runtime/실주문으로 연결하지 않는다(STEP12-3 이후). USER는 이
API에 접근할 수 없다(조회 전용 Strategy Draft API만 유지).

STEP12-2-3A: STRATEGY_DRAFT_GENERATION_STARTED Audit은
`StrategyDraftGenerationService.start_generation()` 내부에서 남긴다(API를
거치지 않고 서비스를 직접 호출하는 경로에서도 STARTED가 누락되지 않도록
STEP12-2-3에서 API 레이어에 있던 책임을 서비스로 옮겼다). 이 API는
`start_generation()`을 호출만 할 뿐 STARTED를 별도로 남기지 않는다 —
중복 Audit을 피하기 위함이다. REQUESTED/최종 결과(SUCCEEDED 등) Audit은
여전히 이 API 레이어에서 남긴다(HTTP 요청 맥락에 한정된 이벤트이므로).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.ai.strategy_draft_generation.service import (
    StrategyDraftGenerationError,
    StrategyDraftGenerationService,
)
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/strategy-draft-generations",
    tags=["Admin Strategy Draft Generations"],
    dependencies=[Depends(require_admin)],
)

# Candidate/Strategy Request가 AI 호출 도중 무효화된 경우 — FAILED와 구분해
# INVALIDATED로 감사 로깅한다.
_INVALIDATION_CODES = frozenset(
    {
        "STRATEGY_REQUEST_NOT_APPROVED",
        "STRATEGY_REQUEST_NOT_FOUND",
        "CANDIDATE_NOT_ACTIVE_AT_DRAFT",
        "CANDIDATE_FINGERPRINT_CHANGED",
        "CANDIDATE_NOT_FOUND",
    }
)


class CreateGenerationBody(BaseModel):
    strategy_request_id: int = Field(gt=0)
    provider_id: str | None = None
    model: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=64)


def _audit(
    session: Session, *, event_type: str, actor: str, detail: dict[str, Any]
) -> None:
    try:
        AuditLogService(session).record(
            event_type=event_type,
            actor=actor,
            detail=sanitize_for_log(detail),
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


def _raise(exc: StrategyDraftGenerationError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code in {"NOT_FOUND", "STRATEGY_REQUEST_NOT_FOUND", "CANDIDATE_NOT_FOUND"}:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {
        "INVALID_STATE_TRANSITION",
        "STRATEGY_REQUEST_NOT_APPROVED",
        "CANDIDATE_NOT_ACTIVE_AT_DRAFT",
        "CANDIDATE_FINGERPRINT_CHANGED",
        "DUPLICATE_ACTIVE_GENERATION_RUN",
    }:
        code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


def _result_event_type(run: dict[str, Any]) -> str:
    status_value = run.get("status")
    if status_value == "SUCCEEDED":
        return "STRATEGY_DRAFT_GENERATION_SUCCEEDED"
    if status_value == "TIMED_OUT":
        return "STRATEGY_DRAFT_GENERATION_TIMED_OUT"
    if run.get("error_code") in _INVALIDATION_CODES:
        return "STRATEGY_DRAFT_GENERATION_INVALIDATED"
    return "STRATEGY_DRAFT_GENERATION_FAILED"


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_generation(
    body: CreateGenerationBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(admin)
    svc = StrategyDraftGenerationService(session)

    try:
        created = svc.create_generation_run(
            strategy_request_id=body.strategy_request_id,
            actor=actor,
            idempotency_key=body.idempotency_key,
            provider_id=body.provider_id,
            model=body.model,
        )
    except StrategyDraftGenerationError as exc:
        event = (
            "STRATEGY_DRAFT_GENERATION_DUPLICATE_BLOCKED"
            if exc.code == "DUPLICATE_ACTIVE_GENERATION_RUN"
            else "STRATEGY_DRAFT_GENERATION_REQUESTED"
        )
        _audit(
            session,
            event_type=event,
            actor=actor,
            detail={
                "strategy_request_id": body.strategy_request_id,
                "code": exc.code,
                "message": exc.message,
            },
        )
        _raise(exc)
        return {}

    _audit(
        session,
        event_type="STRATEGY_DRAFT_GENERATION_REQUESTED",
        actor=actor,
        detail={
            "generation_run_id": created.get("generation_run_id"),
            "strategy_request_id": body.strategy_request_id,
            "provider": created.get("provider"),
            "model": created.get("model"),
        },
    )

    if created.get("idempotent_replay") and created["status"] != "PENDING":
        # 동일 idempotency_key로 이미 종결/진행 중인 Run — 새로 시작하지 않는다.
        return {"run": created, "draft": None, "idempotent_replay": True}

    run_id = created["generation_run_id"]
    # STEP12-2-3A: STARTED Audit은 start_generation() 내부에서 남긴다(API
    # 경로든 직접 서비스 호출이든 항상 기록되도록 서비스 레이어로 이동).
    svc.start_generation(run_id, actor=actor)

    result = await svc.generate(run_id, actor=actor)
    run = result["run"]
    _audit(
        session,
        event_type=_result_event_type(run),
        actor=actor,
        detail={
            "generation_run_id": run.get("generation_run_id"),
            "draft_id": run.get("draft_id"),
            "error_code": run.get("error_code"),
        },
    )
    result["idempotent_replay"] = False
    return result


@router.get("")
def list_generations(
    strategy_request_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return StrategyDraftGenerationService(session).list_generation_runs(
        strategy_request_id=strategy_request_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}")
def get_generation(
    run_id: int,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(admin)
    try:
        result = StrategyDraftGenerationService(session).get_generation_run(run_id)
    except StrategyDraftGenerationError as exc:
        _raise(exc)
        return {}
    _audit(
        session,
        event_type="STRATEGY_DRAFT_GENERATION_VIEWED",
        actor=actor,
        detail={"generation_run_id": run_id},
    )
    return result


@router.get("/{run_id}/attempts")
def list_generation_attempts(
    run_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """STEP12-2-3 §12 — Attempt 목록 전용 조회."""
    try:
        return StrategyDraftGenerationService(session).list_attempts(run_id)
    except StrategyDraftGenerationError as exc:
        _raise(exc)
    return {}


@router.post("/{run_id}/retry", status_code=status.HTTP_201_CREATED)
async def retry_generation(
    run_id: int,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(admin)
    svc = StrategyDraftGenerationService(session)
    try:
        created = svc.retry_generation(run_id, actor=actor)
    except StrategyDraftGenerationError as exc:
        for event in (
            "STRATEGY_DRAFT_GENERATION_FAILED",
            "STRATEGY_DRAFT_REGENERATION_FAILED",
        ):
            _audit(
                session,
                event_type=event,
                actor=actor,
                detail={
                    "retry_of_run_id": run_id,
                    "code": exc.code,
                    "message": exc.message,
                },
            )
        _raise(exc)
        return {}

    for event in (
        "STRATEGY_DRAFT_GENERATION_RETRIED",
        "STRATEGY_DRAFT_REGENERATION_REQUESTED",
    ):
        _audit(
            session,
            event_type=event,
            actor=actor,
            detail={
                "retry_of_run_id": run_id,
                "generation_run_id": created.get("generation_run_id"),
            },
        )

    new_run_id = created["generation_run_id"]
    # STEP12-2-3A: STARTED Audit은 start_generation() 내부에서 남긴다.
    svc.start_generation(new_run_id, actor=actor)

    result = await svc.generate(new_run_id, actor=actor)
    run = result["run"]
    _audit(
        session,
        event_type=_result_event_type(run),
        actor=actor,
        detail={
            "generation_run_id": run.get("generation_run_id"),
            "draft_id": run.get("draft_id"),
            "error_code": run.get("error_code"),
        },
    )
    return result
