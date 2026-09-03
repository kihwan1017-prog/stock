"""Admin News Intelligence Pipeline status/run API — SHADOW ONLY."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.news.collector_scheduler import (
    upbit_news_notice_collector_scheduler,
)
from stock_platform.news.intelligence.kiwoom_scheduler import (
    kiwoom_top10_news_dart_scheduler,
)
from stock_platform.news.intelligence.upbit_targets import (
    list_upbit_dynamic_news_targets,
)
from stock_platform.news.symbol_mapper import mapping_status_snapshot
from stock_platform.operation.news_intelligence_shadow.service import (
    NewsIntelligenceShadowService,
)


router = APIRouter(
    prefix="/api/v1/admin/news-intelligence",
    tags=["Admin News Intelligence"],
    dependencies=[Depends(require_admin)],
)


class KiwoomCollectRequest(BaseModel):
    include_news: bool = True
    include_dart: bool = True


@router.get("/status")
def news_intelligence_status(
    session: Session = Depends(get_db_session),
) -> dict:
    upbit = upbit_news_notice_collector_scheduler.status()
    kiwoom = kiwoom_top10_news_dart_scheduler.status()
    shadow = NewsIntelligenceShadowService(session).status_snapshot()
    mapping = mapping_status_snapshot(session)
    dynamic = list_upbit_dynamic_news_targets(session, limit=8)
    articles_total = int(mapping.get("articles_total") or 0)
    mapped = int(mapping.get("mapped_articles") or 0)
    mapping_rate = (
        round(mapped / float(articles_total), 4) if articles_total else None
    )
    # KIWOOM LLM 관측성 — News shadow N과 Dual-LLM invocation을 분리
    from stock_platform.common.settings import get_settings
    from stock_platform.operation.news_intelligence_shadow.entities import (
        NewsIntelligenceShadowDecisionEntity,
    )
    from sqlalchemy import select

    settings = get_settings()
    kiwoom_shadow_n = int(((shadow.get("kiwoom") or {}).get("n")) or 0)
    kiwoom_rows = list(
        session.scalars(
            select(NewsIntelligenceShadowDecisionEntity).where(
                NewsIntelligenceShadowDecisionEntity.market_code == "KIWOOM"
            )
        )
    )
    llm_backed = sum(
        1
        for r in kiwoom_rows
        if isinstance(r.provenance, dict) and bool(r.provenance.get("llm_backed"))
    )
    return {
        "pipeline_version": "news_intelligence_pipeline_v1",
        "real_gate_coupled": False,
        "upbit_collector": upbit,
        "kiwoom_collector": kiwoom,
        "shadow": shadow,
        "upbit_dynamic_targets": {
            "n": len(dynamic),
            "items": dynamic,
        },
        "symbol_mapping": {
            **mapping,
            "mapping_rate": mapping_rate,
        },
        "kiwoom_llm": {
            "LLM_CONFIGURED": bool(
                getattr(settings, "kiwoom_dual_llm_shadow_enabled", True)
                and getattr(settings, "dual_llm_ollama_enabled", True)
            ),
            "LLM_AVAILABLE": bool(
                str(getattr(settings, "ollama_base_url", "") or "").strip()
            ),
            "LLM_LAST_INVOCATION": None,
            "LLM_LAST_SUCCESS": None,
            "LLM_LAST_ERROR": None,
            "LLM_RUNNING": False,
            "LLM_IDLE_REASON": "NO_FRESH_GOLDEN_CROSS_OR_MARKET_CLOSED_EXPECTED",
            "SHADOW_N": kiwoom_shadow_n,
            "LLM_BACKED_SHADOW_N": llm_backed,
            "note": (
                "News Intelligence shadow N includes non-LLM OBSERVE provenance. "
                "Dual-LLM invocation requires Fresh Golden Cross (market hours)."
            ),
        },
        "freshness_contract": {
            "LAST_CHECK": "collector tick attempted",
            "LAST_SUCCESS": "collector tick without failure",
            "LAST_NEW_ITEM": "actual new article insert time",
            "duplicates_only_success_is_not_stale": True,
        },
    }


@router.post("/kiwoom/run")
async def run_kiwoom_collect(
    body: KiwoomCollectRequest | None = None,
) -> dict:
    """수동 TOP10 news/DART 수집 1회 — REAL 주문/ Fresh Cross 비연동."""

    req = body or KiwoomCollectRequest()
    result = await kiwoom_top10_news_dart_scheduler.run_once_now(
        include_news=bool(req.include_news),
        include_dart=bool(req.include_dart),
    )
    return {
        "status": kiwoom_top10_news_dart_scheduler.status(),
        "result": result,
        "real_order_forced": False,
        "real_fresh_golden_cross_coupled": False,
    }
