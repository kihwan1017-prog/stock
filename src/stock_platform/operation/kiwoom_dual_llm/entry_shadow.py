"""KIWOOM ENTRY SHADOW pipeline — fail-open, non-blocking vs REAL MA path."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.dual_llm.markets import MARKET_KIWOOM
from stock_platform.operation.dual_llm.prompt_versions import (
    SCHEMA_KIWOOM_RAG_V1,
    prompt_versions_for,
)
from stock_platform.operation.kiwoom_dual_llm.analysis_service import (
    run_kiwoom_analysis_llm,
)
from stock_platform.operation.kiwoom_dual_llm.clean_research import (
    classify_kiwoom_research_row,
)
from stock_platform.operation.kiwoom_dual_llm.context_adapter import (
    build_kiwoom_research_context,
)
from stock_platform.operation.kiwoom_dual_llm.rag_store import (
    retrieve_kiwoom_similar_cases,
)
from stock_platform.operation.kiwoom_dual_llm.trading_shadow import (
    run_kiwoom_trading_llm_shadow,
)
from stock_platform.operation.upbit_market_context.entities import (
    UpbitLlmContextAnalysisEntity,
)
from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    record_rag_cache_hit,
)
from stock_platform.operation.upbit_market_context.teacher_llm import (
    run_teacher_review,
    should_call_teacher,
)
from stock_platform.realtime.strategy_signal import StrategySignal


def kiwoom_entry_shadow_enabled() -> bool:
    s = get_settings()
    return bool(getattr(s, "kiwoom_dual_llm_shadow_enabled", True)) and bool(
        getattr(s, "dual_llm_ollama_enabled", True)
    )


def run_kiwoom_entry_shadow(session: Session, signal: StrategySignal) -> dict[str, Any]:
    """동기 연구 파이프라인 — 호출측에서 백그라운드로 실행할 것."""

    if not kiwoom_entry_shadow_enabled():
        return {"ok": False, "skipped": True, "reason": "KIWOOM_SHADOW_DISABLED"}
    if str(signal.signal_type or "").upper() != "BUY":
        return {"ok": False, "skipped": True, "reason": "NOT_BUY"}
    if str(signal.broker_code or "").upper() != "KIWOOM":
        return {"ok": False, "skipped": True, "reason": "NOT_KIWOOM"}

    ctx = build_kiwoom_research_context(session, signal=signal)
    detected = signal.event_time or signal.generated_at or datetime.now(timezone.utc)
    if detected.tzinfo is None:
        detected = detected.replace(tzinfo=timezone.utc)

    analysis = run_kiwoom_analysis_llm(ctx)
    try:
        rag = retrieve_kiwoom_similar_cases(
            session,
            detected_at=detected,
            technical=ctx.get("technical"),
            candidate=ctx.get("candidate"),
            analysis=analysis,
            market=MARKET_KIWOOM,
        )
        if rag.get("cache_hit"):
            record_rag_cache_hit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("kiwoom_rag_failed_open", error=type(exc).__name__)
        rag = {
            "ok": False,
            "market": MARKET_KIWOOM,
            "examples": [],
            "error": type(exc).__name__,
            "no_lookahead": True,
            "clean_only": True,
            "cross_market_rag_count": 0,
        }

    # cross-market 사례 절대 차단
    examples = [
        e
        for e in (rag.get("examples") or [])
        if str(e.get("market") or "").upper() == MARKET_KIWOOM
    ]

    trading = run_kiwoom_trading_llm_shadow(
        ctx,
        analysis_summary=analysis,
        rag_examples=examples,
    )

    teacher_block: dict[str, Any] | None = None
    decide = should_call_teacher(
        analysis=analysis,
        trading=trading,
        feedback=None,
        parse_ok=bool(trading.get("ok")),
    )
    if decide.get("trigger"):
        try:
            teacher_block = run_teacher_review(
                analysis=analysis,
                trading=trading,
                rag_examples=examples,
                feedback=None,
                trigger_reasons=list(decide.get("reasons") or []),
            )
            if isinstance(teacher_block, dict):
                teacher_block["market"] = MARKET_KIWOOM
        except Exception as exc:  # noqa: BLE001
            teacher_block = {
                "ok": False,
                "error": type(exc).__name__,
                "is_ground_truth": False,
                "market": MARKET_KIWOOM,
            }
    else:
        teacher_block = {
            "ok": False,
            "skipped": True,
            "trigger": False,
            "reasons": decide.get("reasons") or [],
            "deferred": bool(decide.get("deferred")),
            "is_ground_truth": False,
            "market": MARKET_KIWOOM,
        }

    prompts = prompt_versions_for(MARKET_KIWOOM)
    out_payload = {
        "schema_version": SCHEMA_KIWOOM_RAG_V1,
        "market": MARKET_KIWOOM,
        "mode": "SHADOW",
        "affects_real": False,
        "analysis_llm": analysis,
        "rag": {
            "market": MARKET_KIWOOM,
            "retrieval_method": rag.get("retrieval_method"),
            "top_k": rag.get("top_k"),
            "examples": examples,
            "cache_hit": bool(rag.get("cache_hit")),
            "no_lookahead": True,
            "clean_only": True,
            "cross_market_rag_count": int(rag.get("cross_market_rag_count") or 0),
        },
        "trading_llm_shadow": trading,
        "teacher_review": teacher_block,
        "outcome_status": "PENDING",
        "prompt_versions": prompts,
        "comparison": {
            "real_path_recommendation": "BUY",  # REAL already decided
            "trading_shadow_recommendation": trading.get("recommendation"),
            "shadow_only": True,
            "real_policy_changed": False,
            "ma_evaluator_unaffected": True,
        },
        "latency_ms": {
            "analysis": analysis.get("latency_ms"),
            "trading_shadow": trading.get("latency_ms"),
        },
    }
    # recommendation 컬럼: SHADOW 연구값 (REAL path 미연결)
    rec = str(trading.get("recommendation") or "HOLD")
    try:
        conf = float(trading.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    score = trading.get("entry_quality_score")

    cls = classify_kiwoom_research_row(input_json=ctx, output_json=out_payload)
    out_payload["clean_classification"] = cls
    out_payload["dataset_tier"] = "EXCLUDED"  # outcome 전 — 이후 feedback에서 승격

    ent = UpbitLlmContextAnalysisEntity(
        symbol=str(signal.symbol).upper(),
        shadow_id=None,
        detected_at=detected,
        context_as_of=detected,
        input_json=ctx,
        output_json=out_payload,
        recommendation=rec,
        confidence=conf,
        entry_quality_score=int(score) if score is not None else None,
        quality="KIWOOM_SHADOW",
        lookahead_ok=True,
        research_only=True,
    )
    session.add(ent)
    session.flush()
    return {
        "ok": True,
        "market": MARKET_KIWOOM,
        "analysis_id": int(ent.analysis_id),
        "trading_shadow_recommendation": trading.get("recommendation"),
        "trading_shadow_ok": bool(trading.get("ok")),
        "analysis_ok": bool(analysis.get("ok")),
        "mode": "SHADOW",
        "REAL_POLICY_CHANGED": "NO",
        "KIWOOM_TRADING_MUTATION": 0,
        "affects_ma_evaluator": False,
    }


def schedule_kiwoom_entry_shadow(signal: StrategySignal) -> None:
    """REAL publish와 독립 — 별도 thread + session. 예외 swallow."""

    if not kiwoom_entry_shadow_enabled():
        return
    if str(signal.signal_type or "").upper() != "BUY":
        return
    if str(signal.broker_code or "").upper() != "KIWOOM":
        return

    def _worker() -> None:
        session = get_session_factory()()
        try:
            result = run_kiwoom_entry_shadow(session, signal)
            session.commit()
            logger.info(
                "kiwoom_entry_shadow_done",
                ok=result.get("ok"),
                analysis_id=result.get("analysis_id"),
                symbol=signal.symbol,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "kiwoom_entry_shadow_failed_open",
                error=type(exc).__name__,
                symbol=getattr(signal, "symbol", None),
            )
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
        finally:
            session.close()

    try:
        threading.Thread(
            target=_worker,
            name="kiwoom-dual-llm-shadow",
            daemon=True,
        ).start()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "kiwoom_entry_shadow_schedule_failed",
            error=type(exc).__name__,
        )
