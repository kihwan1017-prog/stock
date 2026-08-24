"""Admin Dual LLM role status — READ ONLY.

Prefix: /api/v1/admin/upbit/dual-llm
WRITE/mutate 없음. REAL/LIVE 무관.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session
from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    analysis_config,
    runtime_stats,
    trading_config,
)
from stock_platform.operation.upbit_market_context.dual_llm_shadow_outcomes import (
    build_heuristic_vs_llm_shadow,
    promotion_status,
)
from stock_platform.operation.upbit_market_context.entities import (
    UpbitLlmContextAnalysisEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    assign_clean_forward_obs,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)

router = APIRouter(
    prefix="/api/v1/admin/upbit/dual-llm",
    tags=["Admin Upbit Dual LLM"],
    dependencies=[Depends(require_admin)],
)


@router.get("/status")
def dual_llm_status(session: Session = Depends(get_db_session)) -> dict[str, Any]:
    s = get_settings()
    a_cfg = analysis_config()
    t_cfg = trading_config()
    stats = runtime_stats()

    completed = list(
        session.scalars(
            select(UpbitOpportunityShadowEntity).where(
                UpbitOpportunityShadowEntity.deleted_at.is_(None),
                UpbitOpportunityShadowEntity.status == SHADOW_STATUS_COMPLETED,
            )
        )
    )
    clean_n = len(assign_clean_forward_obs(completed))

    dual_n = 0
    try:
        rows = list(
            session.scalars(
                select(UpbitLlmContextAnalysisEntity)
                .order_by(desc(UpbitLlmContextAnalysisEntity.created_at))
                .limit(500)
            )
        )
        dual_n = sum(
            1
            for r in rows
            if isinstance(r.output_json, dict)
            and r.output_json.get("schema_version") == "upbit_dual_llm_shadow_v1"
        )
    except Exception:  # noqa: BLE001
        session.rollback()
        dual_n = 0

    return {
        "schema": "upbit_dual_llm_status_v1",
        "research_only": True,
        "ANALYSIS_LLM_MODEL": a_cfg.model,
        "TRADING_LLM_MODEL": t_cfg.model,
        "REFERENCE_MODEL": s.ollama_model,
        "ANALYSIS_LLM_WIRED": True,
        "TRADING_LLM_WIRED": True,
        "TRADING_LLM_MODE": "SHADOW",
        "dual_llm_ollama_enabled": bool(s.dual_llm_ollama_enabled),
        "trading_llm_shadow_enabled": bool(s.trading_llm_shadow_enabled),
        "TRADING_PRIORITY_IMPLEMENTED": True,
        "ANALYSIS_CACHE_IMPLEMENTED": True,
        "PROTECTIVE_EXIT_LLM_DEPENDENCY": False,
        "analysis": {
            "model": a_cfg.model,
            "timeout_seconds": a_cfg.timeout_seconds,
            "temperature": a_cfg.temperature,
            "max_tokens": a_cfg.max_tokens,
            "calls": stats["analysis_calls"],
            "ok": stats["analysis_ok"],
            "timeouts": stats["analysis_timeout"],
            "errors": stats["analysis_error"],
            "cache_hits": stats["analysis_cache_hit"],
            "median_latency_ms": stats["analysis_median_latency_ms"],
        },
        "trading_shadow": {
            "model": t_cfg.model,
            "mode": "SHADOW",
            "timeout_seconds": t_cfg.timeout_seconds,
            "temperature": t_cfg.temperature,
            "max_tokens": t_cfg.max_tokens,
            "calls": stats["trading_shadow_calls"],
            "ok": stats["trading_shadow_ok"],
            "timeouts": stats["trading_shadow_timeout"],
            "errors": stats["trading_shadow_error"],
            "median_latency_ms": stats["trading_median_latency_ms"],
        },
        "dual_llm_rows_stored": dual_n,
        **promotion_status(clean_n),
        "REAL_POLICY_CHANGED": "NO",
        "REAL_ORDER_MUTATION": 0,
        "LIVE_ARM_MUTATION": 0,
        "RISK_MUTATION": 0,
        "SLOT_POLICY_MUTATION": 0,
        "KIWOOM_MUTATION": 0,
    }


@router.get("/recent")
def dual_llm_recent(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(UpbitLlmContextAnalysisEntity)
            .order_by(desc(UpbitLlmContextAnalysisEntity.created_at))
            .limit(limit)
        )
    )
    items = []
    for r in rows:
        out = r.output_json if isinstance(r.output_json, dict) else {}
        analysis = out.get("analysis_llm") if isinstance(out.get("analysis_llm"), dict) else {}
        trading = (
            out.get("trading_llm_shadow")
            if isinstance(out.get("trading_llm_shadow"), dict)
            else {}
        )
        heur = (
            out.get("current_heuristic")
            if isinstance(out.get("current_heuristic"), dict)
            else {}
        )
        items.append(
            {
                "analysis_id": int(r.analysis_id),
                "shadow_id": r.shadow_id,
                "symbol": r.symbol,
                "context_as_of": r.context_as_of.isoformat() if r.context_as_of else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "dual_schema": out.get("schema_version") == "upbit_dual_llm_shadow_v1",
                "heuristic_recommendation": heur.get("recommendation") or r.recommendation,
                "heuristic_score": heur.get("entry_quality_score") or r.entry_quality_score,
                "analysis_model": analysis.get("model"),
                "analysis_ok": analysis.get("ok"),
                "analysis_latency_ms": analysis.get("latency_ms"),
                "market_summary": analysis.get("market_summary"),
                "news_summary": analysis.get("news_summary"),
                "trading_model": trading.get("model"),
                "trading_mode": trading.get("mode") or "SHADOW",
                "trading_recommendation": trading.get("recommendation"),
                "entry_quality_score": trading.get("entry_quality_score"),
                "early_dump_risk": trading.get("early_dump_risk"),
                "trading_confidence": trading.get("confidence"),
                "trading_latency_ms": trading.get("latency_ms"),
                "trading_ok": trading.get("ok"),
                "agree": (out.get("comparison") or {}).get("agree"),
                "lookahead_ok": bool(r.lookahead_ok),
            }
        )
    return {
        "schema": "upbit_dual_llm_recent_v1",
        "research_only": True,
        "items": items,
        "total": len(items),
    }


@router.get("/comparison")
def dual_llm_comparison(
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return build_heuristic_vs_llm_shadow(session)
