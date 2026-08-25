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
