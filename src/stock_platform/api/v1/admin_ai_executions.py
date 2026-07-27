"""STEP 11-5 — Admin AI Execution API."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.execution.recovery import recover_stale_executions
from stock_platform.ai.execution.runner import AIExecutionRunner
from stock_platform.ai.execution.service import (
    AIExecutionError,
    AIExecutionService,
)
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/ai/executions",
    tags=["Admin AI Executions"],
    dependencies=[Depends(require_admin)],
)


class CreateBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=64)
    task_type: str
    execution_mode: str = "MOCK"
    input_payload: dict[str, Any] = Field(default_factory=dict)
    provider_code: str | None = None
    requested_model: str | None = None
    prompt_template_id: int | None = None
    prompt_version_id: int | None = None
    output_schema_id: int | None = None
    policy_ids: list[int] | None = None
    max_tokens: int = 256
    temperature: float = 0.2
    timeout_sec: float = 30.0
    fallback_enabled: bool = False
    retry_max: int = 1
    budget_limit: float | None = None
    correlation_id: str | None = None


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    confirm: bool = False
    expected_version: int | None = None
    correlation_id: str | None = None


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


def _raise(exc: AIExecutionError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    if exc.code in {"VERSION_CONFLICT", "LEASE_HELD"}:
        code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


@router.get("")
def list_executions(
    limit: int = 50,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIExecutionService(session).list_requests(limit=limit)
    return {"count": len(items), "items": items}


@router.post("/recovery/scan")
def recovery_scan(
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """수동 Recovery 스캔 — 자동 외부 재호출 없음."""

    actor = admin_actor_label(user)
    result = recover_stale_executions(session, actor=actor)
    _audit(
        session,
        event_type="AI_EXECUTION_RECOVERY_REVIEW_REQUIRED",
        actor=actor,
        detail=result,
    )
    return result


@router.post("")
def create_execution(
    body: CreateBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-exec-create:{user.user_id}", limit=20, window_seconds=60
    )
    actor = admin_actor_label(user)
    try:
        result = AIExecutionService(session).create_request(
            actor=actor,
            reason=body.reason,
            task_type=body.task_type,
            execution_mode=body.execution_mode,
            idempotency_key=body.idempotency_key,
            input_payload=body.input_payload,
            provider_code=body.provider_code,
            requested_model=body.requested_model,
            prompt_template_id=body.prompt_template_id,
            prompt_version_id=body.prompt_version_id,
            output_schema_id=body.output_schema_id,
            policy_ids=body.policy_ids,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            timeout_sec=body.timeout_sec,
            fallback_enabled=body.fallback_enabled,
            retry_max=body.retry_max,
            budget_limit=body.budget_limit,
            correlation_id=body.correlation_id or str(uuid4()),
        )
    except AIExecutionError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_EXECUTION_CREATED",
        actor=actor,
        detail={
            "id": (result.get("request") or {}).get("id"),
            "task_type": body.task_type,
            "mode": body.execution_mode,
            "auto_executed": False,
        },
    )
    return result


@router.get("/{request_id}")
def get_execution(
    request_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        req = AIExecutionService(session).get_request(request_id)
    except AIExecutionError as exc:
        _raise(exc)
        raise
    svc = AIExecutionService(session)
    return {
        "request": req,
        "runs": svc.list_runs(request_id),
        "result": svc.get_result(request_id),
        "events": svc.list_events(request_id),
    }


@router.post("/{request_id}/dry-run")
def dry_run(
    request_id: int,
    body: ReasonBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-exec-dry:{user.user_id}", limit=30, window_seconds=60
    )
    actor = admin_actor_label(user)
    try:
        result = AIExecutionRunner(session).dry_run(request_id, actor=actor)
    except AIExecutionError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_EXECUTION_DRY_RUN_COMPLETED",
        actor=actor,
        detail={
            "id": request_id,
            "ok": result.get("ok"),
            "external_ai_called": False,
        },
    )
    return result


@router.post("/{request_id}/execute")
async def execute(
    request_id: int,
    body: ReasonBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-exec-run:{user.user_id}", limit=10, window_seconds=60
    )
    actor = admin_actor_label(user)
    try:
        result = await AIExecutionRunner(session).execute(
            request_id,
            actor=actor,
            confirm=body.confirm,
            expected_version=body.expected_version,
        )
    except AIExecutionError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_EXECUTION_COMPLETED",
        actor=actor,
        detail={
            "id": request_id,
            "ok": result.get("ok"),
            "external_ai_called": result.get("external_ai_called"),
            "mock_called": result.get("mock_called"),
        },
    )
    return result


@router.post("/{request_id}/cancel")
def cancel(
    request_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIExecutionService(session).cancel(
            request_id,
            actor=actor,
            reason=body.reason,
            expected_version=body.expected_version,
        )
    except AIExecutionError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_EXECUTION_CANCELLED",
        actor=actor,
        detail={"id": request_id, "cost_refund": False},
    )
    return result


@router.post("/{request_id}/retry-as-new")
def retry_as_new(
    request_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """실패 Request를 복사해 새 Request 생성 (자동 실행 없음)."""

    actor = admin_actor_label(user)
    svc = AIExecutionService(session)
    try:
        old = svc.get_request(request_id)
    except AIExecutionError as exc:
        _raise(exc)
        raise
    from stock_platform.ai.execution.entities import AIExecutionRequestEntity

    row = session.get(AIExecutionRequestEntity, request_id)
    assert row is not None
    try:
        result = svc.create_request(
            actor=actor,
            reason=body.reason,
            task_type=row.task_type,
            execution_mode=row.execution_mode,
            idempotency_key=f"retry:{request_id}:{uuid4().hex[:12]}",
            input_payload=row.input_payload_sanitized or {},
            provider_code=row.provider_code,
            requested_model=row.requested_model,
            prompt_template_id=row.prompt_template_id,
            prompt_version_id=row.prompt_version_id,
            output_schema_id=row.output_schema_id,
            policy_ids=list(row.policy_ids or []),
            max_tokens=row.max_tokens,
            temperature=row.temperature,
            timeout_sec=row.timeout_sec,
            fallback_enabled=row.fallback_enabled,
            retry_max=row.retry_max,
            budget_limit=row.budget_limit,
        )
    except AIExecutionError as exc:
        _raise(exc)
        raise
    return {**result, "retried_from": old.get("id"), "auto_executed": False}


@router.get("/{request_id}/runs")
def get_runs(
    request_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIExecutionService(session).list_runs(request_id)
    return {"count": len(items), "items": items}


@router.get("/{request_id}/result")
def get_result(
    request_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    result = AIExecutionService(session).get_result(request_id)
    return {"result": result}


@router.get("/{request_id}/events")
def get_events(
    request_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIExecutionService(session).list_events(request_id)
    return {"count": len(items), "items": items}


# costs under same admin ai prefix via separate routes on same router file
costs_router = APIRouter(
    prefix="/api/v1/admin/ai/costs",
    tags=["Admin AI Costs"],
    dependencies=[Depends(require_admin)],
)


@costs_router.get("/summary")
def costs_summary(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AIExecutionService(session).costs_summary()


@costs_router.get("/by-provider")
def costs_by_provider(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AIExecutionService(session).costs_summary()


@costs_router.get("/by-model")
def costs_by_model(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    # 간단 요약 — model 세부는 runs 집계로 확장 가능
    return {
        **AIExecutionService(session).costs_summary(),
        "note": "by-model detail uses operator pricing estimates only",
    }
