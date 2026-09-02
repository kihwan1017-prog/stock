"""Admin Upbit Research Detail Workspace — READ ONLY APIs.

Prefix: /api/v1/admin/upbit/research
WRITE / mutate endpoint 없음. REAL/LIVE/정책 무관.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.operation.upbit_market_context import research_detail_workspace as rdw

router = APIRouter(
    prefix="/api/v1/admin/upbit/research",
    tags=["Admin Upbit Research Detail"],
    dependencies=[Depends(require_admin)],
)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


@router.get("/clean-forward")
def list_clean_forward(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    symbol: str | None = Query(default=None),
    recommendation: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    early_dump: bool | None = Query(default=None),
    data_quality: str | None = Query(default=None),
    detected_from: str | None = Query(default=None),
    detected_to: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return rdw.list_clean_forward(
        session,
        page=page,
        page_size=page_size,
        symbol=symbol,
        recommendation=recommendation,
        outcome=outcome,
        early_dump=early_dump,
        data_quality=data_quality,
        detected_from=_parse_dt(detected_from),
        detected_to=_parse_dt(detected_to),
    )


@router.get("/clean-forward/{shadow_id}")
def get_clean_forward_detail(
    shadow_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    detail = rdw.get_clean_forward_detail(session, shadow_id=shadow_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail="CLEAN forward row not found (legacy/backfill/non-clean excluded)",
        )
    return detail


@router.get("/market-context")
def list_market_context(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    feature_key: str | None = Query(default=None),
    collected_from: str | None = Query(default=None),
    collected_to: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return rdw.list_market_context(
        session,
        page=page,
        page_size=page_size,
        feature_key=feature_key,
        collected_from=_parse_dt(collected_from),
        collected_to=_parse_dt(collected_to),
    )


@router.get("/asset-context")
def list_asset_context(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    symbol: str | None = Query(default=None),
    collected_from: str | None = Query(default=None),
    collected_to: str | None = Query(default=None),
    rank_min: int | None = Query(default=None),
    rank_max: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return rdw.list_asset_context(
        session,
        page=page,
        page_size=page_size,
        symbol=symbol,
        collected_from=_parse_dt(collected_from),
        collected_to=_parse_dt(collected_to),
        rank_min=rank_min,
        rank_max=rank_max,
    )


@router.get("/news")
def list_news(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    symbol: str | None = Query(default=None),
    source_type: str | None = Query(default=None, description="NEWS | NOTICE"),
    published_from: str | None = Query(default=None),
    published_to: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return rdw.list_news_notice(
        session,
        page=page,
        page_size=page_size,
        symbol=symbol,
        source_type=source_type,
        published_from=_parse_dt(published_from),
        published_to=_parse_dt(published_to),
    )


@router.get("/llm-analysis")
def list_llm_analysis(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    symbol: str | None = Query(default=None),
    recommendation: str | None = Query(default=None),
    shadow_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return rdw.list_llm_analysis(
        session,
        page=page,
        page_size=page_size,
        symbol=symbol,
        recommendation=recommendation,
        shadow_id=shadow_id,
    )


@router.get("/llm-analysis/{analysis_id}")
def get_llm_analysis_detail(
    analysis_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    detail = rdw.get_llm_analysis_detail(session, analysis_id=analysis_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="LLM analysis not found")
    return detail


@router.get("/experiments")
def get_experiments(
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return rdw.get_filter_experiments(session)


@router.get("/ma-exit-forward-shadow/summary")
def get_ma_exit_forward_shadow_summary(
    uba_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.summary import (
        summarize_forward_shadow,
    )

    return summarize_forward_shadow(
        session, user_broker_account_id=uba_id
    )


@router.get("/ma-exit-forward-shadow/rows")
def list_ma_exit_forward_shadow_rows(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    uba_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.summary import (
        list_forward_shadow_rows,
    )

    return list_forward_shadow_rows(
        session,
        user_broker_account_id=uba_id,
        page=page,
        page_size=page_size,
    )


@router.get("/entry-signal-shadow/summary")
def get_entry_signal_shadow_summary(
    uba_id: int = Query(default=1380, ge=1),
    include_replay: bool = Query(default=True),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Entry Signal Shadow E0–E4 — RESEARCH_ONLY, REAL policy unchanged."""

    from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.summary import (
        summarize_entry_signal_shadow,
    )

    return summarize_entry_signal_shadow(
        session,
        user_broker_account_id=uba_id,
        include_replay=include_replay,
    )


@router.get("/short-term-turnover/summary")
def get_short_term_turnover_summary() -> dict[str, Any]:
    """WRK-015 Upbit short-term turnover research — READ ONLY evidence."""

    from stock_platform.operation.upbit_short_term_turnover.summary import (
        summarize_for_ui,
    )

    return summarize_for_ui()


@router.get("/positive-edge-entry/summary")
def get_positive_edge_entry_summary() -> dict[str, Any]:
    """WRK-016 positive-edge entry discovery — READ ONLY evidence."""

    from stock_platform.operation.upbit_positive_edge_entry.summary import (
        summarize_for_ui,
    )

    return summarize_for_ui()


@router.get("/h2-h3-forward-shadow/summary")
def get_h2_h3_forward_shadow_summary(
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """WRK-019 H2/H3 frozen forward-shadow — RESEARCH ONLY."""

    from stock_platform.operation.upbit_h2_h3_forward_shadow.summary import (
        summarize_for_ui,
    )

    return summarize_for_ui(session)


@router.get("/exit-strategy-shadow/summary")
def get_exit_strategy_shadow_summary(
    uba_id: int | None = Query(default=1380),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """WRK Exit Strategy Shadow V1 — RESEARCH ONLY (no REAL promote)."""

    from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.summary import (
        summarize_exit_strategy_shadow,
    )

    return summarize_exit_strategy_shadow(
        session,
        user_broker_account_id=int(uba_id) if uba_id else None,
    )


@router.get("/exit-strategy-shadow/entry/{entry_order_id}")
def get_exit_strategy_shadow_entry_detail(
    entry_order_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """단일 natural BUY에 대한 exit family 비교."""

    from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.summary import (
        entry_detail_comparison,
    )

    return entry_detail_comparison(session, entry_order_id=int(entry_order_id))


@router.get("/exit-optimization-lab/summary")
def get_exit_optimization_lab_summary(
    uba_id: int | None = Query(default=1380),
    include_rows: bool = Query(default=False),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Exit Optimization Shadow Lab V2 — T0/T5/T6/T7/T8 + readiness (RESEARCH)."""

    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
        summarize_exit_optimization_lab,
    )

    return summarize_exit_optimization_lab(
        session,
        user_broker_account_id=int(uba_id) if uba_id else None,
        include_rows=bool(include_rows),
    )


@router.post("/exit-optimization-lab/reconcile-baselines")
def post_exit_optimization_lab_reconcile(
    uba_id: int | None = Query(default=1380),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """기존 forward T5 row에 canonical baseline ledger 연결 (backfill virtual exit 금지)."""

    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
        reconcile_existing_forward_baselines,
        summarize_exit_optimization_lab,
    )

    result = reconcile_existing_forward_baselines(
        session,
        user_broker_account_id=int(uba_id) if uba_id else None,
        limit=int(limit),
    )
    session.commit()
    summary = summarize_exit_optimization_lab(
        session,
        user_broker_account_id=int(uba_id) if uba_id else None,
    )
    return {"ok": True, "reconcile": result, "summary": summary}


@router.get("/waiting-lifecycle-lab/summary")
def get_waiting_lifecycle_lab_summary(
    uba_id: int | None = Query(default=1380),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Waiting Lifecycle Forward Shadow Lab V1 summary (research only)."""

    from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.service import (
        summarize_waiting_lifecycle_lab,
    )

    return summarize_waiting_lifecycle_lab(
        session,
        user_broker_account_id=int(uba_id or 1380),
    )


@router.get("/waiting-lifecycle-lab/observations")
def get_waiting_lifecycle_lab_observations(
    uba_id: int | None = Query(default=1380),
    variant: str | None = Query(default=None),
    cohort: str | None = Query(default=None),
    status: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.service import (
        list_observations,
    )

    return list_observations(
        session,
        user_broker_account_id=int(uba_id or 1380),
        variant=variant,
        cohort=cohort,
        status=status,
        symbol=symbol,
        limit=limit,
        offset=offset,
    )


@router.get("/waiting-lifecycle-lab/comparison")
def get_waiting_lifecycle_lab_comparison(
    uba_id: int | None = Query(default=1380),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.service import (
        compare_variants,
    )

    return compare_variants(
        session, user_broker_account_id=int(uba_id or 1380)
    )


@router.get("/exit-order-recovery-lab/summary")
def get_exit_order_recovery_lab_summary(
    uba_id: int | None = Query(default=1380),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Exit Order Recovery Shadow Lab V1 — RESEARCH ONLY (REAL policy 불변)."""

    from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service import (
        summarize_exit_order_recovery_lab,
    )

    return summarize_exit_order_recovery_lab(
        session,
        user_broker_account_id=int(uba_id or 1380),
    )


@router.get("/exit-order-recovery-lab/observations")
def get_exit_order_recovery_lab_observations(
    uba_id: int | None = Query(default=1380),
    variant: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service import (
        list_observations,
    )

    return list_observations(
        session,
        user_broker_account_id=int(uba_id or 1380),
        variant=variant,
        limit=limit,
    )


@router.get("/exit-order-recovery-lab/comparison")
def get_exit_order_recovery_lab_comparison(
    uba_id: int | None = Query(default=1380),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service import (
        compare_variants,
    )

    return compare_variants(
        session, user_broker_account_id=int(uba_id or 1380)
    )


@router.get("/exit-optimization-v3/summary")
def get_exit_optimization_v3_summary(
    uba_id: int | None = Query(default=1380),
    include_rows: bool = Query(default=False),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Exit Optimization Shadow Lab V3 — R0/E1–E4 (RESEARCH)."""

    from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.service import (
        summarize_exit_optimization_v3_lab,
    )

    return summarize_exit_optimization_v3_lab(
        session,
        user_broker_account_id=int(uba_id) if uba_id else None,
        include_rows=bool(include_rows),
    )


@router.get("/exit-optimization-v3/variants")
def get_exit_optimization_v3_variants(
    uba_id: int | None = Query(default=1380),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.service import (
        summarize_exit_optimization_v3_lab,
    )

    summary = summarize_exit_optimization_v3_lab(
        session, user_broker_account_id=int(uba_id) if uba_id else None
    )
    return {
        "ok": True,
        "VARIANTS": summary.get("VARIANTS"),
        "VARIANT_LABELS": summary.get("VARIANT_LABELS"),
    }


@router.get("/exit-optimization-v3/comparison")
def get_exit_optimization_v3_comparison(
    uba_id: int | None = Query(default=1380),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.service import (
        summarize_exit_optimization_v3_lab,
    )

    return summarize_exit_optimization_v3_lab(
        session,
        user_broker_account_id=int(uba_id) if uba_id else None,
        include_rows=True,
        row_limit=100,
    )


@router.get("/exit-optimization-v3/observations")
def get_exit_optimization_v3_observations(
    uba_id: int | None = Query(default=1380),
    variant: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.service import (
        list_observations,
    )

    return list_observations(
        session,
        user_broker_account_id=int(uba_id) if uba_id else None,
        variant=variant,
        limit=int(limit),
        offset=int(offset),
    )


@router.get("/exit-optimization-lab/reentry-summary")
def get_exit_optimization_reentry_summary(
    uba_id: int | None = Query(default=1380),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Post-exit re-entry cooldown shadow R0–R3 summary."""

    from stock_platform.operation.upbit_opportunity_shadow.reentry_cooldown_shadow.service import (
        summarize_reentry_cooldown,
    )

    return summarize_reentry_cooldown(
        session,
        user_broker_account_id=int(uba_id) if uba_id else None,
    )


@router.get("/profitability-lab/summary")
def get_profitability_lab_summary(
    uba_id: int | None = Query(default=1380),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Profitability Improvement Shadow Lab V1 — Candidate/Exit/Reentry."""

    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.service import (
        summarize_profitability_lab,
    )

    return summarize_profitability_lab(
        session, user_broker_account_id=int(uba_id or 1380)
    )


@router.get("/profitability-lab/candidates")
def get_profitability_lab_candidates(
    uba_id: int | None = Query(default=1380),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.service import (
        summarize_candidates,
    )

    return summarize_candidates(session, user_broker_account_id=int(uba_id or 1380))


@router.get("/profitability-lab/exits")
def get_profitability_lab_exits(
    uba_id: int | None = Query(default=1380),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.service import (
        summarize_exits,
    )

    return summarize_exits(session, user_broker_account_id=int(uba_id or 1380))


@router.get("/profitability-lab/reentry")
def get_profitability_lab_reentry(
    uba_id: int | None = Query(default=1380),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.service import (
        summarize_reentry,
    )

    return summarize_reentry(session, user_broker_account_id=int(uba_id or 1380))


@router.get("/entry-signal-shadow/rows")
def list_entry_signal_shadow_rows_api(
    uba_id: int = Query(default=1380, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.summary import (
        list_entry_signal_shadow_rows,
    )

    return list_entry_signal_shadow_rows(
        session, user_broker_account_id=uba_id, limit=limit
    )
