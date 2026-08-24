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


@router.get("/market-context/research")
def market_context_research_status(
    session: Session = Depends(get_db_session),
) -> dict:
    """시장·뉴스·LLM 컨텍스트 research 현황 — REAL 정책/주문 무관."""

    from stock_platform.operation.upbit_market_context.early_dump_research import (
        early_dump_research_design,
    )
    from stock_platform.operation.upbit_market_context.schemas import (
        LLM_INPUT_SCHEMA_DOC,
        LLM_OUTPUT_SCHEMA_DOC,
    )
    from stock_platform.operation.upbit_market_context.source_registry import (
        source_audit_report,
    )
    from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
        assign_clean_forward_obs,
        partition_forward_rows,
    )
    from stock_platform.operation.upbit_opportunity_shadow.constants import (
        SHADOW_STATUS_COMPLETED,
    )
    from stock_platform.operation.upbit_opportunity_shadow.entities import (
        UpbitOpportunityShadowEntity,
    )
    from sqlalchemy import select

    audit = source_audit_report()
    clean_n = 0
    try:
        rows = list(
            session.scalars(
                select(UpbitOpportunityShadowEntity).where(
                    UpbitOpportunityShadowEntity.deleted_at.is_(None),
                    UpbitOpportunityShadowEntity.status == SHADOW_STATUS_COMPLETED,
                )
            )
        )
        part = partition_forward_rows(rows)
        clean_n = int(part.get("clean_new_count") or 0)
        _ = assign_clean_forward_obs(rows)
    except Exception as exc:  # noqa: BLE001
        part = {"error": str(exc)[:120]}

    # latest market snapshots (fail-open if table missing)
    latest: dict = {}
    try:
        from stock_platform.operation.upbit_market_context.entities import (
            UpbitMarketContextSnapshotEntity,
        )

        for key in (
            "fear_greed",
            "advancing_asset_ratio",
            "24h_turnover",
            "market_return",
        ):
            row = session.scalar(
                select(UpbitMarketContextSnapshotEntity)
                .where(UpbitMarketContextSnapshotEntity.feature_key == key)
                .order_by(UpbitMarketContextSnapshotEntity.source_timestamp.desc())
                .limit(1)
            )
            if row is not None:
                latest[key] = {
                    "quality": row.quality,
                    "value": row.value_json,
                    "source_timestamp": (
                        row.source_timestamp.isoformat()
                        if row.source_timestamp
                        else None
                    ),
                    "source": row.source,
                }
    except Exception as exc:  # noqa: BLE001
        latest = {"error": type(exc).__name__, "detail": str(exc)[:120]}

    return {
        "schema": "upbit_market_context_research_status_v1",
        "research_only": True,
        "live_order": False,
        "REAL_POLICY_CHANGED": "NO",
        "CLEAN_SAMPLE_COUNT": clean_n,
        "cohort_partition": {
            "CLEAN_FORWARD": clean_n,
            "detail": {
                k: part.get(k)
                for k in (
                    "legacy_total",
                    "new_stamped_count",
                    "clean_new_count",
                    "clean_epoch_start",
                )
                if isinstance(part, dict)
            },
        },
        "source_audit": audit,
        "latest_market_features": latest,
        "LLM_INPUT_SCHEMA": LLM_INPUT_SCHEMA_DOC,
        "LLM_OUTPUT_SCHEMA": LLM_OUTPUT_SCHEMA_DOC,
        "EARLY_DUMP_RESEARCH_DESIGN": early_dump_research_design(),
        "dashboard": {
            "title_ko": "시장·뉴스 분석 (연구)",
            "market_mood": _mood_from_latest(latest),
            "fear_greed": (latest.get("fear_greed") or {}).get("value"),
            "advancing": (latest.get("advancing_asset_ratio") or {}).get("value"),
            "turnover": (latest.get("24h_turnover") or {}).get("value"),
        },
        "mutations": {
            "REAL_ORDER_MUTATION": 0,
            "REAL_POLICY_MUTATION": 0,
            "RISK_MUTATION": 0,
            "SLOT_MUTATION": 0,
            "UBA1381_MUTATION": 0,
        },
    }


def _mood_from_latest(latest: dict) -> str:
    adv = ((latest.get("advancing_asset_ratio") or {}).get("value") or {}).get(
        "ratio"
    )
    fg = ((latest.get("fear_greed") or {}).get("value") or {}).get("value")
    try:
        from stock_platform.operation.upbit_market_context.telegram_enrichment import (
            market_mood_ko,
        )

        return market_mood_ko(
            float(adv) if adv is not None else None,
            int(fg) if fg is not None else None,
        )
    except Exception:  # noqa: BLE001
        return "중립"


@router.post("/market-context/collect-once")
def market_context_collect_once(
    session: Session = Depends(get_db_session),
) -> dict:
    """공식 ticker + F&G 1회 수집 — DataLab scrape 없음. 주문 없음."""

    from stock_platform.operation.upbit_market_context.collect_runner import (
        run_market_context_collect,
    )

    try:
        # dry collect: description은 상위 30개만 (TTL 캐시 유지)
        out = run_market_context_collect(
            session,
            include_fear_greed=True,
            description_limit=30,
        )
        session.commit()
        return out
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {
            "ok": False,
            "error": type(exc).__name__,
            "detail": str(exc)[:200],
            "live_order": False,
            "REAL_POLICY_CHANGED": "NO",
            "note": "fail-open research; REAL not blocked",
        }



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
