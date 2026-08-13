"""Admin UPBIT News Combined Shadow Experiment API — EXPERIMENT ONLY (N6)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.operation.upbit_news_combined_shadow.evaluator import (
    UpbitNewsCombinedShadowEvaluator,
)
from stock_platform.operation.upbit_news_combined_shadow.scheduler import (
    upbit_news_combined_shadow_scheduler,
)
from stock_platform.operation.upbit_news_combined_shadow.service import (
    UpbitNewsCombinedShadowService,
    experiment_stats_snapshot,
    list_recent_experiments,
)


router = APIRouter(
    prefix="/api/v1/admin/upbit/combined-shadow",
    tags=["Admin Upbit News Combined Shadow Experiment"],
    dependencies=[Depends(require_admin)],
)


class CombinedShadowRunRequest(BaseModel):
    limit_runs: int = Field(default=5, ge=1, le=20)
    scanner_run_ids: list[str] | None = None
    force: bool = False


class CombinedShadowEvaluateRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=100)


@router.get("/status")
def combined_shadow_status(session: Session = Depends(get_db_session)) -> dict:
    snap = experiment_stats_snapshot(session)
    snap["scheduler"] = upbit_news_combined_shadow_scheduler.status()
    return snap


@router.get("/recent")
def combined_shadow_recent(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> dict:
    items = list_recent_experiments(session, limit=limit)
    return {
        "items": items,
        "count": len(items),
        "experiment_only": True,
        "informational_only": True,
        "scanner_apply": False,
        "control_mutation": False,
        "llm_calls": 0,
    }


@router.get("/stats")
def combined_shadow_stats(session: Session = Depends(get_db_session)) -> dict:
    return experiment_stats_snapshot(session)


@router.post("/run")
def combined_shadow_run(
    body: CombinedShadowRunRequest | None = None,
    session: Session = Depends(get_db_session),
) -> dict:
    """CONTROL Shadow READ → EXPERIMENT rows. CONTROL mutation 없음."""

    req = body or CombinedShadowRunRequest()
    service = UpbitNewsCombinedShadowService(session)
    stats = service.run_from_control_shadows(
        limit_runs=req.limit_runs,
        scanner_run_ids=req.scanner_run_ids,
        force=bool(req.force),
    )
    return {
        "result": asdict(stats),
        "status": experiment_stats_snapshot(session),
        "scheduler": upbit_news_combined_shadow_scheduler.status(),
        "llm_calls": 0,
        "control_mutated": False,
        "shadow_control_mutated": False,
        "scanner_mutated": False,
        "orders_created": 0,
        "experiment_only": True,
    }


@router.post("/evaluate")
def combined_shadow_evaluate(
    body: CombinedShadowEvaluateRequest | None = None,
    session: Session = Depends(get_db_session),
) -> dict:
    req = body or CombinedShadowEvaluateRequest()
    evaluator = UpbitNewsCombinedShadowEvaluator(session)
    result = evaluator.evaluate_pending(limit=req.limit)
    return {
        "result": result,
        "status": experiment_stats_snapshot(session),
        "control_mutated": False,
        "llm_calls": 0,
        "experiment_only": True,
    }
