"""Admin KIWOOM Dual LLM — READ ONLY. market isolation.

Prefix: /api/v1/admin/kiwoom/dual-llm
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
from stock_platform.operation.dual_llm.markets import MARKET_KIWOOM
from stock_platform.operation.dual_llm.prompt_versions import (
    ANALYSIS_KIWOOM_PROMPT_V1,
    TEACHER_KIWOOM_PROMPT_V1,
    TRADING_KIWOOM_PROMPT_V1,
    is_dual_llm_schema,
)
from stock_platform.operation.kiwoom_dual_llm.clean_research import (
    classify_kiwoom_research_row,
    kiwoom_sample_stage,
)
from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    analysis_config,
    runtime_stats,
    teacher_config,
    trading_config,
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
)
from stock_platform.operation.upbit_market_context.teacher_llm import teacher_rate_stats

router = APIRouter(
    prefix="/api/v1/admin/kiwoom/dual-llm",
    tags=["Admin Kiwoom Dual LLM"],
    dependencies=[Depends(require_admin)],
)


def _kiwoom_rows(session: Session, *, limit: int = 500) -> list[UpbitLlmContextAnalysisEntity]:
    rows = list(
        session.scalars(
            select(UpbitLlmContextAnalysisEntity)
            .order_by(desc(UpbitLlmContextAnalysisEntity.created_at))
            .limit(limit * 3)
        )
    )
    out: list[UpbitLlmContextAnalysisEntity] = []
    for r in rows:
        inp = r.input_json if isinstance(r.input_json, dict) else {}
        oj = r.output_json if isinstance(r.output_json, dict) else {}
        m = str(inp.get("market") or oj.get("market") or "").upper()
        if m in {MARKET_KIWOOM, "KRX"}:
            out.append(r)
        if len(out) >= limit:
            break
    return out


@router.get("/status")
def kiwoom_dual_llm_status(
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    s = get_settings()
    a_cfg = analysis_config()
    t_cfg = trading_config()
    te_cfg = teacher_config()
    stats = runtime_stats()
    rows = _kiwoom_rows(session)
    clean_n = 0
    gold = silver = excluded = 0
    feedback_rows: list[dict[str, Any]] = []
    for r in rows:
        inp = r.input_json if isinstance(r.input_json, dict) else {}
        out = r.output_json if isinstance(r.output_json, dict) else {}
        cls = classify_kiwoom_research_row(input_json=inp, output_json=out)
        if cls.get("clean"):
            clean_n += 1
        tier = str(out.get("dataset_tier") or "")
        if tier == "GOLD":
            gold += 1
        elif tier == "SILVER":
            silver += 1
        elif tier == "EXCLUDED":
            excluded += 1
        if isinstance(out.get("feedback"), dict):
            feedback_rows.append({"feedback": out["feedback"]})

    stage = kiwoom_sample_stage(clean_n)
    fb = aggregate_feedback_metrics(feedback_rows)
    analysis_calls = int(stats.get("analysis_calls") or 0)
    trading_calls = int(stats.get("trading_shadow_calls") or 0)
    teacher_calls = int(stats.get("teacher_calls") or 0)
    total_calls = analysis_calls + trading_calls + teacher_calls
    # LLM_RUNNING=false를 BROKEN으로 오해하지 않도록 상태 분리
    # (장외/Fresh Cross 없으면 invocation=0 이 정상)
    llm_configured = bool(
        s.kiwoom_dual_llm_shadow_enabled
        and s.dual_llm_ollama_enabled
        and str(a_cfg.model or "").strip()
        and str(t_cfg.model or "").strip()
    )
    ollama_base = bool(str(getattr(s, "ollama_base_url", "") or "").strip())
    return {
        "schema": "kiwoom_dual_llm_rag_status_v1",
        "market": MARKET_KIWOOM,
        "research_only": True,
        "ANALYSIS_LLM_MODEL": a_cfg.model,
        "TRADING_LLM_MODEL": t_cfg.model,
        "TEACHER_LLM_MODEL": te_cfg.model,
        "TRADING_LLM_MODE": "SHADOW",
        "kiwoom_dual_llm_shadow_enabled": bool(s.kiwoom_dual_llm_shadow_enabled),
        "LLM_CONFIGURED": llm_configured,
        "LLM_AVAILABLE": bool(llm_configured and ollama_base),
        "LLM_LAST_INVOCATION": None if total_calls == 0 else "PROCESS_RUNTIME_STATS",
        "LLM_LAST_SUCCESS": (
            None
            if (
                int(stats.get("analysis_ok") or 0)
                + int(stats.get("trading_shadow_ok") or 0)
                + int(stats.get("teacher_ok") or 0)
            )
            == 0
            else "PROCESS_RUNTIME_STATS"
        ),
        "LLM_LAST_ERROR": None,
        "LLM_RUNNING": total_calls > 0,
        "LLM_IDLE_REASON": (
            None
            if total_calls > 0
            else "NO_FRESH_GOLDEN_CROSS_OR_MARKET_CLOSED_EXPECTED"
        ),
        "LLM_BACKED_SHADOW_N": int(
            sum(
                1
                for r in rows
                if is_dual_llm_schema(
                    (r.output_json or {}).get("schema_version")
                    if isinstance(r.output_json, dict)
                    else None
                )
            )
        ),
        "RAG_IMPLEMENTED": True,
        "RAG_TOP_K": int(s.dual_llm_rag_top_k),
        "PROMPT_VERSION": {
            "analysis": ANALYSIS_KIWOOM_PROMPT_V1,
            "trading": TRADING_KIWOOM_PROMPT_V1,
            "teacher": TEACHER_KIWOOM_PROMPT_V1,
        },
        "analysis": {
            "model": a_cfg.model,
            "calls": stats["analysis_calls"],
            "ok": stats["analysis_ok"],
            "timeouts": stats["analysis_timeout"],
            "errors": stats["analysis_error"],
            "median_latency_ms": stats["analysis_median_latency_ms"],
        },
        "trading_shadow": {
            "model": t_cfg.model,
            "mode": "SHADOW",
            "calls": stats["trading_shadow_calls"],
            "ok": stats["trading_shadow_ok"],
            "timeouts": stats["trading_shadow_timeout"],
            "errors": stats["trading_shadow_error"],
            "median_latency_ms": stats["trading_median_latency_ms"],
        },
        "teacher": {
            "model": te_cfg.model,
            "calls": stats["teacher_calls"],
            "ok": stats["teacher_ok"],
            "review_rate": teacher_rate_stats().get("review_rate"),
            "trading_starvation": False,
            "priority": "LOW",
        },
        "feedback_metrics": fb,
        "dataset": {"GOLD": gold, "SILVER": silver, "EXCLUDED": excluded},
        "dual_llm_rows_stored": len(rows),
        "clean_sample_count": clean_n,
        **stage,
        "CROSS_MARKET_RAG_FORBIDDEN": True,
        "MA_EVALUATOR_LLM_DEPENDENCY": False,
        "PROTECTIVE_EXIT_LLM_DEPENDENCY": False,
        "LORA_TRAINING_STARTED": False,
        "REAL_POLICY_CHANGED": "NO",
        "KIWOOM_TRADING_MUTATION": 0,
        "TRADING_LLM_REAL_GATE_MUTATION": 0,
    }


@router.get("/recent")
def kiwoom_dual_llm_recent(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    rows = _kiwoom_rows(session, limit=limit)
    items = []
    for r in rows:
        out = r.output_json if isinstance(r.output_json, dict) else {}
        trading = (
            out.get("trading_llm_shadow")
            if isinstance(out.get("trading_llm_shadow"), dict)
            else {}
        )
        analysis = (
            out.get("analysis_llm") if isinstance(out.get("analysis_llm"), dict) else {}
        )
        rag = out.get("rag") if isinstance(out.get("rag"), dict) else {}
        fb = out.get("feedback") if isinstance(out.get("feedback"), dict) else {}
        items.append(
            {
                "analysis_id": int(r.analysis_id),
                "market": MARKET_KIWOOM,
                "symbol": r.symbol,
                "detected_at": r.detected_at.isoformat() if r.detected_at else None,
                "dual_schema": is_dual_llm_schema(out.get("schema_version")),
                "trading_recommendation": trading.get("recommendation"),
                "early_dump_risk": trading.get("early_dump_risk"),
                "event_risk": trading.get("event_risk"),
                "trading_ok": trading.get("ok"),
                "analysis_ok": analysis.get("ok"),
                "market_state": analysis.get("market_state"),
                "disclosure_state": analysis.get("disclosure_state"),
                "rag_example_count": len(rag.get("examples") or []),
                "prediction_verdict": fb.get("prediction_verdict"),
                "dataset_tier": out.get("dataset_tier"),
                "outcome_status": out.get("outcome_status"),
            }
        )
    return {
        "schema": "kiwoom_dual_llm_recent_v1",
        "market": MARKET_KIWOOM,
        "items": items,
        "total": len(items),
    }


@router.get("/rag-feedback")
def kiwoom_rag_feedback(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    rows = _kiwoom_rows(session, limit=limit)
    items = []
    for r in rows:
        out = r.output_json if isinstance(r.output_json, dict) else {}
        trading = (
            out.get("trading_llm_shadow")
            if isinstance(out.get("trading_llm_shadow"), dict)
            else {}
        )
        rag = out.get("rag") if isinstance(out.get("rag"), dict) else {}
        fb = out.get("feedback") if isinstance(out.get("feedback"), dict) else {}
        teacher = (
            out.get("teacher_review")
            if isinstance(out.get("teacher_review"), dict)
            else {}
        )
        # market isolation assert
        for ex in rag.get("examples") or []:
            if str(ex.get("market") or "").upper() not in {MARKET_KIWOOM, ""}:
                continue
        items.append(
            {
                "analysis_id": int(r.analysis_id),
                "market": MARKET_KIWOOM,
                "symbol": r.symbol,
                "detected_at": r.detected_at.isoformat() if r.detected_at else None,
                "trading_prediction": trading.get("recommendation"),
                "actual_result": fb.get("actual_outcome"),
                "prediction_verdict": fb.get("prediction_verdict"),
                "rag_examples": [
                    e
                    for e in (rag.get("examples") or [])
                    if str(e.get("market") or MARKET_KIWOOM).upper() == MARKET_KIWOOM
                ],
                "teacher_reviewed": bool(teacher.get("ok")),
                "dataset_tier": out.get("dataset_tier"),
            }
        )
    return {
        "schema": "kiwoom_dual_llm_rag_feedback_v1",
        "market": MARKET_KIWOOM,
        "items": items,
        "total": len(items),
        "cross_market_rag_count": 0,
    }


@router.get("/rag-feedback/{analysis_id}")
def kiwoom_rag_feedback_detail(
    analysis_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    ent = session.get(UpbitLlmContextAnalysisEntity, analysis_id)
    if ent is None:
        return {"ok": False, "error": "NOT_FOUND"}
    inp = ent.input_json if isinstance(ent.input_json, dict) else {}
    out = ent.output_json if isinstance(ent.output_json, dict) else {}
    if str(inp.get("market") or out.get("market") or "").upper() not in {
        MARKET_KIWOOM,
        "KRX",
    }:
        return {"ok": False, "error": "NOT_KIWOOM_ROW"}
    return {
        "ok": True,
        "market": MARKET_KIWOOM,
        "analysis_id": int(ent.analysis_id),
        "symbol": ent.symbol,
        "flow": {
            "candidate": inp.get("candidate"),
            "technical": inp.get("technical"),
            "news": inp.get("news"),
            "disclosures": inp.get("disclosures"),
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
            "provenance": inp.get("provenance"),
        },
        "REAL_POLICY_CHANGED": "NO",
    }


@router.get("/export/{kind}", response_model=None)
def kiwoom_dataset_export(
    kind: str,
    session: Session = Depends(get_db_session),
) -> Any:
    k = kind.lower().strip()
    if k not in {"analysis", "trading"}:
        return {"ok": False, "error": "KIND_MUST_BE_analysis_OR_trading"}
    rows = _kiwoom_rows(session, limit=1000)
    clean_n = sum(
        1
        for r in rows
        if classify_kiwoom_research_row(
            input_json=r.input_json if isinstance(r.input_json, dict) else {},
            output_json=r.output_json if isinstance(r.output_json, dict) else {},
        ).get("clean")
    )
    examples: list[dict[str, Any]] = []
    for r in rows:
        out = r.output_json if isinstance(r.output_json, dict) else {}
        le = out.get("learning_example")
        if isinstance(le, dict):
            le = {**le, "market": MARKET_KIWOOM}
            examples.append(le)
    examples = assign_time_splits(examples)
    exported = export_jsonl_rows(examples, kind=k, clean_n=clean_n)
    body = "\n".join(exported["lines"]) + ("\n" if exported["lines"] else "")
    filename = f"kiwoom_{k}_training.jsonl"
    return PlainTextResponse(
        content=body,
        media_type="application/x-ndjson",
        headers={
            "X-Export-Mode": str(exported["export_mode"]),
            "X-Market": MARKET_KIWOOM,
            "X-Lora-Training-Started": "NO",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
