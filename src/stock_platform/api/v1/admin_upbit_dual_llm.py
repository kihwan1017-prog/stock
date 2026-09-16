"""Admin Dual LLM + RAG/Feedback — READ ONLY (export JSONL 포함).

Prefix: /api/v1/admin/upbit/dual-llm
REAL/LIVE mutate 없음.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session
from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    analysis_config,
    runtime_stats,
    teacher_config,
    trading_config,
)
from stock_platform.operation.upbit_market_context.dual_llm_shadow_outcomes import (
    build_heuristic_vs_llm_shadow,
    promotion_status,
)
from stock_platform.operation.upbit_market_context.entities import (
    UpbitLlmContextAnalysisEntity,
)
from stock_platform.operation.upbit_market_context.feedback_scoring import (
    aggregate_feedback_metrics,
)
from stock_platform.operation.upbit_market_context.learning_dataset import (
    assign_time_splits,
    export_jsonl_rows,
    sample_stage,
)
from stock_platform.operation.upbit_market_context.prompt_versions import (
    ANALYSIS_PROMPT_VERSION,
    TEACHER_PROMPT_VERSION,
    TRADING_PROMPT_VERSION,
    is_dual_llm_schema,
)
from stock_platform.operation.upbit_market_context.rag_retrieval import rag_cache
from stock_platform.operation.upbit_market_context.teacher_llm import teacher_rate_stats
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


def _dual_rows(session: Session, *, limit: int = 500) -> list[UpbitLlmContextAnalysisEntity]:
    return list(
        session.scalars(
            select(UpbitLlmContextAnalysisEntity)
            .order_by(desc(UpbitLlmContextAnalysisEntity.created_at))
            .limit(limit)
        )
    )


@router.get("/status")
def dual_llm_status(session: Session = Depends(get_db_session)) -> dict[str, Any]:
    s = get_settings()
    a_cfg = analysis_config()
    t_cfg = trading_config()
    te_cfg = teacher_config()
    stats = runtime_stats()
    t_rate = teacher_rate_stats()

    completed = list(
        session.scalars(
            select(UpbitOpportunityShadowEntity).where(
                UpbitOpportunityShadowEntity.deleted_at.is_(None),
                UpbitOpportunityShadowEntity.status == SHADOW_STATUS_COMPLETED,
            )
        )
    )
    clean_n = len(assign_clean_forward_obs(completed))
    stage = sample_stage(clean_n)

    dual_n = 0
    feedback_rows: list[dict[str, Any]] = []
    rag_hits = 0
    rag_with_ex = 0
    gold = silver = excluded = 0
    try:
        rows = _dual_rows(session)
        for r in rows:
            out = r.output_json if isinstance(r.output_json, dict) else {}
            if not is_dual_llm_schema(out.get("schema_version")):
                continue
            dual_n += 1
            rag = out.get("rag") if isinstance(out.get("rag"), dict) else {}
            if rag.get("cache_hit"):
                rag_hits += 1
            if rag.get("examples"):
                rag_with_ex += 1
            if isinstance(out.get("feedback"), dict):
                feedback_rows.append(
                    {
                        "feedback": out["feedback"],
                        "shadow_id": r.shadow_id,
                    }
                )
            tier = str(out.get("dataset_tier") or "")
            if tier == "GOLD":
                gold += 1
            elif tier == "SILVER":
                silver += 1
            elif tier == "EXCLUDED":
                excluded += 1
    except Exception:  # noqa: BLE001
        session.rollback()
        dual_n = 0

    fb_metrics = aggregate_feedback_metrics(feedback_rows)
    avg_sim_cases = None
    if dual_n:
        # rough: rows with examples / dual
        avg_sim_cases = round(rag_with_ex / dual_n, 4)

    return {
        "schema": "upbit_dual_llm_rag_status_v1",
        "research_only": True,
        "ANALYSIS_LLM_MODEL": a_cfg.model,
        "TRADING_LLM_MODEL": t_cfg.model,
        "TEACHER_LLM_MODEL": te_cfg.model,
        "REFERENCE_MODEL": s.ollama_model,
        "ANALYSIS_LLM_WIRED": True,
        "TRADING_LLM_WIRED": True,
        "TEACHER_LLM_WIRED": True,
        "TRADING_LLM_MODE": "SHADOW",
        "dual_llm_ollama_enabled": bool(s.dual_llm_ollama_enabled),
        "trading_llm_shadow_enabled": bool(s.trading_llm_shadow_enabled),
        "teacher_llm_enabled": bool(s.teacher_llm_enabled),
        "TRADING_PRIORITY_IMPLEMENTED": True,
        "ANALYSIS_CACHE_IMPLEMENTED": True,
        "RAG_IMPLEMENTED": True,
        "RAG_RETRIEVAL_METHOD": "structured_hybrid_normalized_distance",
        "RAG_TOP_K": int(s.dual_llm_rag_top_k),
        "RAG_CACHE_TTL_SECONDS": float(s.dual_llm_rag_cache_ttl_seconds),
        "PROTECTIVE_EXIT_LLM_DEPENDENCY": False,
        "PROMPT_VERSION": {
            "analysis": ANALYSIS_PROMPT_VERSION,
            "trading": TRADING_PROMPT_VERSION,
            "teacher": TEACHER_PROMPT_VERSION,
        },
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
        "teacher": {
            "model": te_cfg.model,
            "enabled": bool(s.teacher_llm_enabled),
            "max_rate": float(s.teacher_llm_max_rate),
            "calls": stats["teacher_calls"],
            "ok": stats["teacher_ok"],
            "timeouts": stats["teacher_timeout"],
            "errors": stats["teacher_error"],
            "median_latency_ms": stats["teacher_median_latency_ms"],
            "review_rate": t_rate.get("review_rate"),
            "trading_starvation": False,
            "priority": "LOW",
        },
        "rag": {
            "hit_rate": (
                round(rag_cache.hits / max(rag_cache.hits + rag_cache.misses, 1), 4)
            ),
            "cache_hits_runtime": rag_cache.hits,
            "cache_misses_runtime": rag_cache.misses,
            "rows_with_examples": rag_with_ex,
            "average_similar_cases": avg_sim_cases,
        },
        "feedback_metrics": fb_metrics,
        "dataset": {
            "GOLD": gold,
            "SILVER": silver,
            "EXCLUDED": excluded,
        },
        "dual_llm_rows_stored": dual_n,
        **promotion_status(clean_n),
        **stage,
        "REAL_POLICY_CHANGED": "NO",
        "REAL_ORDER_MUTATION": 0,
        "LIVE_ARM_MUTATION": 0,
        "RISK_MUTATION": 0,
        "SLOT_POLICY_MUTATION": 0,
        "KIWOOM_MUTATION": 0,
        "TRADING_LLM_REAL_GATE_MUTATION": 0,
        "LORA_TRAINING_STARTED": False,
    }


@router.get("/recent")
def dual_llm_recent(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    rows = _dual_rows(session, limit=limit)
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
        rag = out.get("rag") if isinstance(out.get("rag"), dict) else {}
        fb = out.get("feedback") if isinstance(out.get("feedback"), dict) else {}
        teacher = (
            out.get("teacher_review")
            if isinstance(out.get("teacher_review"), dict)
            else {}
        )
        items.append(
            {
                "analysis_id": int(r.analysis_id),
                "shadow_id": r.shadow_id,
                "symbol": r.symbol,
                "context_as_of": r.context_as_of.isoformat() if r.context_as_of else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "dual_schema": is_dual_llm_schema(out.get("schema_version")),
                "schema_version": out.get("schema_version"),
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
                "fee_churn_risk": trading.get("fee_churn_risk"),
                "trading_confidence": trading.get("confidence"),
                "trading_latency_ms": trading.get("latency_ms"),
                "trading_ok": trading.get("ok"),
                "agree": (out.get("comparison") or {}).get("agree"),
                "lookahead_ok": bool(r.lookahead_ok),
                "rag_example_count": len(rag.get("examples") or []),
                "prediction_verdict": fb.get("prediction_verdict"),
                "actual_label": (fb.get("actual_outcome") or {}).get("label"),
                "teacher_reviewed": bool(teacher.get("ok")),
                "dataset_tier": out.get("dataset_tier"),
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


@router.get("/rag-feedback")
def dual_llm_rag_feedback(
    limit: int = Query(default=50, ge=1, le=200),
    verdict: str | None = Query(default=None),
    tier: str | None = Query(default=None),
    teacher_reviewed: bool | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """연구 데이터용 RAG/Feedback 목록."""

    rows = _dual_rows(session, limit=400)
    items: list[dict[str, Any]] = []
    for r in rows:
        out = r.output_json if isinstance(r.output_json, dict) else {}
        if not is_dual_llm_schema(out.get("schema_version")):
            continue
        fb = out.get("feedback") if isinstance(out.get("feedback"), dict) else {}
        trading = (
            out.get("trading_llm_shadow")
            if isinstance(out.get("trading_llm_shadow"), dict)
            else {}
        )
        rag = out.get("rag") if isinstance(out.get("rag"), dict) else {}
        teacher = (
            out.get("teacher_review")
            if isinstance(out.get("teacher_review"), dict)
            else {}
        )
        analysis = (
            out.get("analysis_llm") if isinstance(out.get("analysis_llm"), dict) else {}
        )
        pv = str(fb.get("prediction_verdict") or "")
        dtier = str(out.get("dataset_tier") or "")
        trev = bool(teacher.get("ok"))
        if verdict and verdict.upper() not in pv.upper():
            continue
        if tier and tier.upper() != dtier.upper():
            continue
        if teacher_reviewed is not None and trev != teacher_reviewed:
            continue
        items.append(
            {
                "analysis_id": int(r.analysis_id),
                "shadow_id": r.shadow_id,
                "symbol": r.symbol,
                "detected_at": r.context_as_of.isoformat() if r.context_as_of else None,
                "trading_prediction": trading.get("recommendation"),
                "confidence": trading.get("confidence"),
                "early_dump_risk": trading.get("early_dump_risk"),
                "fee_churn_risk": trading.get("fee_churn_risk"),
                "actual_result": fb.get("actual_outcome"),
                "prediction_verdict": pv or None,
                "rag_examples": rag.get("examples") or [],
                "analysis_tone": analysis.get("tone"),
                "teacher_reviewed": trev,
                "teacher_preferred": (teacher.get("review") or {}).get(
                    "preferred_recommendation"
                )
                if isinstance(teacher.get("review"), dict)
                else None,
                "dataset_tier": dtier or None,
                "learning_example": out.get("learning_example"),
            }
        )
        if len(items) >= limit:
            break

    return {
        "schema": "upbit_dual_llm_rag_feedback_v1",
        "research_only": True,
        "items": items,
        "total": len(items),
        "filters": {
            "verdict": verdict,
            "tier": tier,
            "teacher_reviewed": teacher_reviewed,
        },
    }


@router.get("/rag-feedback/{analysis_id}")
def dual_llm_rag_feedback_detail(
    analysis_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    ent = session.get(UpbitLlmContextAnalysisEntity, analysis_id)
    if ent is None:
        return {"ok": False, "error": "NOT_FOUND"}
    out = ent.output_json if isinstance(ent.output_json, dict) else {}
    return {
        "ok": True,
        "schema": "upbit_dual_llm_rag_feedback_detail_v1",
        "analysis_id": int(ent.analysis_id),
        "shadow_id": ent.shadow_id,
        "symbol": ent.symbol,
        "flow": {
            "candidate": (ent.input_json or {}).get("candidate")
            if isinstance(ent.input_json, dict)
            else None,
            "rag_examples": (out.get("rag") or {}).get("examples")
            if isinstance(out.get("rag"), dict)
            else [],
            "analysis_1_7b": out.get("analysis_llm"),
            "trading_2b": out.get("trading_llm_shadow"),
            "teacher_4b": out.get("teacher_review"),
            "actual_outcome": (out.get("feedback") or {}).get("actual_outcome")
            if isinstance(out.get("feedback"), dict)
            else None,
            "feedback": out.get("feedback"),
            "dataset_tier": out.get("dataset_tier"),
            "learning_example": out.get("learning_example"),
        },
        "REAL_POLICY_CHANGED": "NO",
    }


@router.get("/export/{kind}", response_model=None)
def dual_llm_dataset_export(
    kind: str,
    session: Session = Depends(get_db_session),
) -> Any:
    """LoRA prep JSONL — 학습 실행 없음. analysis|trading만."""

    k = kind.lower().strip()
    if k not in {"analysis", "trading"}:
        return {"ok": False, "error": "KIND_MUST_BE_analysis_OR_trading"}

    completed = list(
        session.scalars(
            select(UpbitOpportunityShadowEntity).where(
                UpbitOpportunityShadowEntity.deleted_at.is_(None),
                UpbitOpportunityShadowEntity.status == SHADOW_STATUS_COMPLETED,
            )
        )
    )
    clean_n = len(assign_clean_forward_obs(completed))

    examples: list[dict[str, Any]] = []
    for r in _dual_rows(session, limit=1000):
        out = r.output_json if isinstance(r.output_json, dict) else {}
        le = out.get("learning_example")
        if isinstance(le, dict):
            examples.append(le)
    examples = assign_time_splits(examples)
    exported = export_jsonl_rows(examples, kind=k, clean_n=clean_n)
    body = "\n".join(exported["lines"]) + ("\n" if exported["lines"] else "")
    filename = f"training_{k}.jsonl"
    return PlainTextResponse(
        content=body,
        media_type="application/x-ndjson",
        headers={
            "X-Export-Mode": str(exported["export_mode"]),
            "X-Lora-Training-Started": "NO",
            "X-Dataset-Kind": k,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
