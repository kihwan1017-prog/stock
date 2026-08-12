"""Admin UPBIT Opportunity Scanner API — Alert-only + Paper Shadow."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
    upbit_opportunity_scanner_scheduler,
)
from stock_platform.operation.upbit_opportunity_shadow import (
    UpbitOpportunityShadowEvaluator,
    UpbitOpportunityShadowReconciliationService,
    UpbitOpportunityShadowService,
    compute_shadow_stats,
)
from stock_platform.operation.upbit_opportunity_shadow.evaluator_scheduler import (
    upbit_opportunity_shadow_evaluator_scheduler,
)


router = APIRouter(
    prefix="/api/v1/admin/upbit/opportunity-scanner",
    tags=["Admin Upbit Opportunity Scanner"],
    dependencies=[Depends(require_admin)],
)


class ScannerRunRequest(BaseModel):
    notify: bool = True
    force_ai: bool = False


@router.get("/status")
def scanner_status(session: Session = Depends(get_db_session)) -> dict:
    status = upbit_opportunity_scanner_scheduler.status()
    status["evaluator"] = upbit_opportunity_shadow_evaluator_scheduler.status()
    try:
        svc = UpbitOpportunityShadowService(session)
        status["shadows"] = {
            "active": svc.list_shadows(status="ACTIVE", limit=20),
            "completed": svc.list_shadows(status="COMPLETED", limit=20),
            "stats": compute_shadow_stats(session),
        }
    except Exception as exc:  # noqa: BLE001
        status["shadows"] = {"error": type(exc).__name__}
    status["shadow_only"] = True
    status["live_order"] = False
    return status


@router.post("/run")
async def scanner_run_once(body: ScannerRunRequest | None = None) -> dict:
    """수동 1회 Dry Run — 주문/Runtime/LIVE 변경 없음."""

    req = body or ScannerRunRequest()
    result = await upbit_opportunity_scanner_scheduler.run_once_now(
        notify=bool(req.notify),
        force_ai=bool(req.force_ai),
    )
    return {
        "status": upbit_opportunity_scanner_scheduler.status(),
        "result": result,
    }


@router.get("/shadows")
def list_shadows(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> dict:
    svc = UpbitOpportunityShadowService(session)
    items = svc.list_shadows(status=status, limit=limit)
    return {
        "items": items,
        "stats": compute_shadow_stats(session),
        "orders_created": 0,
        "paper_shadow": True,
    }


@router.post("/shadows/evaluate")
async def evaluate_shadows(
    session: Session = Depends(get_db_session),
) -> dict:
    """ACTIVE Shadow 평가만 — AI/주문 없음. historical candle backfill."""

    out = await UpbitOpportunityShadowEvaluator(session).evaluate_pending(
        notify=True
    )
    return out


@router.post("/shadows/evaluate-now")
async def evaluate_shadows_via_scheduler() -> dict:
    """Evaluator scheduler 경로 1회 (mismatch watch 포함)."""

    return await upbit_opportunity_shadow_evaluator_scheduler.run_once_now(
        notify=True
    )


@router.get("/shadows/{shadow_id}/recompute-dry")
async def recompute_shadow_dry(
    shadow_id: int,
    session: Session = Depends(get_db_session),
) -> dict:
    """COMPLETED 포함 historical 재계산 — DB UPDATE 없음."""

    return await UpbitOpportunityShadowEvaluator(session).dry_recompute(
        shadow_id
    )


class ShadowReconcileApplyRequest(BaseModel):
    expected_fingerprint: str
    actor: str = "admin"
    reason: str = "historical_candle_reconciliation"
    approval_phrase: str


@router.post("/shadows/{shadow_id}/reconcile/preview")
async def reconcile_shadow_preview(
    shadow_id: int,
    session: Session = Depends(get_db_session),
) -> dict:
    """COMPLETED Shadow historical reconciliation preview — mutation 0."""

    return await UpbitOpportunityShadowReconciliationService(
        session
    ).preview(shadow_id)


@router.post("/shadows/{shadow_id}/reconcile/apply")
async def reconcile_shadow_apply(
    shadow_id: int,
    body: ShadowReconcileApplyRequest,
    session: Session = Depends(get_db_session),
) -> dict:
    """명시 승인 phrase + fingerprint 일치 시에만 WRITE."""

    return await UpbitOpportunityShadowReconciliationService(session).apply(
        shadow_id,
        expected_fingerprint=body.expected_fingerprint,
        actor=body.actor,
        reason=body.reason,
        approval_phrase=body.approval_phrase,
    )
