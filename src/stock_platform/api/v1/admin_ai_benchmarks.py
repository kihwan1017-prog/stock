"""STEP 11-8 — Admin AI Benchmark / Scorecard API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.ai.review.benchmark_service import AIBenchmarkService
from stock_platform.ai.review.scorecard_service import AIScorecardService
from stock_platform.ai.review.service import AIReviewError
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

benchmarks_router = APIRouter(
    prefix="/api/v1/admin/ai/benchmarks",
    tags=["Admin AI Benchmarks"],
    dependencies=[Depends(require_admin)],
)

scorecards_router = APIRouter(
    prefix="/api/v1/admin/ai/scorecards",
    tags=["Admin AI Scorecards"],
    dependencies=[Depends(require_admin)],
)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    confirm: bool = False


class CreateBenchmarkBody(BaseModel):
    dataset_id: int
    provider_code: str
    model: str
    execution_mode: str = "MOCK"
    prompt_version_id: int | None = None
    output_schema_id: int | None = None
    policy_ids: list[int] | None = None
    max_items: int | None = None
    reason: str = Field(min_length=1, max_length=500)


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


def _raise(exc: AIReviewError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    if exc.code in {"CONFIRM_REQUIRED", "DATASET_INACTIVE", "DATA_POLICY_BLOCKED"}:
        code = status.HTTP_403_FORBIDDEN
    if exc.code == "ALREADY_TERMINAL":
        code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


# --- Benchmarks ---


@benchmarks_router.post("")
def create_benchmark(
    body: CreateBenchmarkBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIBenchmarkService(session).create(
            actor=actor,
            reason=body.reason,
            dataset_id=body.dataset_id,
            provider_code=body.provider_code,
            model=body.model,
            execution_mode=body.execution_mode,
            prompt_version_id=body.prompt_version_id,
            output_schema_id=body.output_schema_id,
            policy_ids=body.policy_ids,
            max_items=body.max_items,
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_BENCHMARK_CREATED",
        actor=actor,
        detail={
            "benchmark_id": result["benchmark"]["id"],
            "dataset_id": body.dataset_id,
            "execution_mode": body.execution_mode,
            "provider_code": body.provider_code,
        },
    )
    return result


@benchmarks_router.get("")
def list_benchmarks(
    limit: int = 50,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIBenchmarkService(session).list_runs(limit=limit)
    return {"count": len(items), "items": items}


@benchmarks_router.get("/dashboard")
def benchmarks_dashboard(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AIBenchmarkService(session).dashboard_summary()


@benchmarks_router.get("/{benchmark_id}")
def get_benchmark(
    benchmark_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return {"benchmark": AIBenchmarkService(session).get(benchmark_id)}
    except AIReviewError as exc:
        _raise(exc)
        raise  # pragma: no cover


@benchmarks_router.post("/{benchmark_id}/dry-run")
def dry_run_benchmark(
    benchmark_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIBenchmarkService(session).dry_run(benchmark_id, actor=actor)
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_BENCHMARK_DRY_RUN_COMPLETED",
        actor=actor,
        detail={
            "benchmark_id": benchmark_id,
            "item_count": result.get("item_count"),
            "reason": body.reason,
        },
    )
    return result


@benchmarks_router.post("/{benchmark_id}/execute")
async def execute_benchmark(
    benchmark_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = await AIBenchmarkService(session).execute(
            benchmark_id, actor=actor, confirm=body.confirm
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_BENCHMARK_COMPLETED",
        actor=actor,
        detail={
            "benchmark_id": benchmark_id,
            "ok": result.get("ok"),
            "external_ai_called": result.get("external_ai_called"),
            "reason": body.reason,
            "confirm": body.confirm,
        },
    )
    return result


@benchmarks_router.post("/{benchmark_id}/cancel")
def cancel_benchmark(
    benchmark_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIBenchmarkService(session).cancel(
            benchmark_id, actor=actor, reason=body.reason
        )
    except AIReviewError as exc:
        _raise(exc)
    _audit(
        session,
        event_type="AI_BENCHMARK_CANCELLED",
        actor=actor,
        detail={"benchmark_id": benchmark_id, "reason": body.reason},
    )
    return result


# --- Scorecards ---


@scorecards_router.get("")
def list_scorecards(
    dataset_id: int | None = None,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AIScorecardService(session).scorecards(dataset_id=dataset_id)


@scorecards_router.get("/compare")
def compare_scorecards(
    left_benchmark_id: int,
    right_benchmark_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AIScorecardService(session).compare(
        left_benchmark_id=left_benchmark_id,
        right_benchmark_id=right_benchmark_id,
    )


@scorecards_router.get("/calibration")
def calibration_summary(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AIScorecardService(session).calibration_summary()
