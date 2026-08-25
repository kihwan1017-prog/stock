"""Candidate-driven dual LLM — heuristic + ANALYSIS + TRADING SHADOW.

Scanner 신규 Shadow 생성 시에만 실행. 전종목 주기 LLM 호출 금지.
TRADING_LLM은 SHADOW ONLY — REAL recommendation/slot/order/LIVE를 변경하지 않는다.
실패 시 fail-open (research_failed_open).
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.operation.upbit_market_context.entities import (
    UpbitLlmContextAnalysisEntity,
)
from stock_platform.operation.upbit_market_context.snapshot_service import (
    MarketContextSnapshotService,
    heuristic_llm_analyze,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)


def maybe_analyze_shadow_candidate(
    session: Session,
    row: UpbitOpportunityShadowEntity,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """단일 Shadow 후보: heuristic 유지 + dual LLM SHADOW 저장.

    실패해도 raise하지 않음 (research_failed_open).
    Shadow entity.recommendation 은 Scanner 원본 유지 (LLM이 overwrite 금지).
    """

    try:
        from stock_platform.common.settings import get_settings

        if not force and not bool(
            getattr(
                get_settings(),
                "upbit_market_context_candidate_llm_enabled",
                True,
            )
        ):
            return {
                "ok": True,
                "skipped": True,
                "reason": "CANDIDATE_LLM_DISABLED",
                "live_order": False,
                "REAL_POLICY_CHANGED": "NO",
            }

        shadow_id = int(row.shadow_id)
        symbol = str(row.symbol or "")
        if not symbol:
            return {"ok": False, "skipped": True, "reason": "NO_SYMBOL"}

        if not force:
            existing = session.scalar(
                select(UpbitLlmContextAnalysisEntity).where(
                    UpbitLlmContextAnalysisEntity.shadow_id == shadow_id
                )
            )
            if existing is not None:
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "ALREADY_ANALYZED",
                    "analysis_id": int(existing.analysis_id),
                    "live_order": False,
                }

        snap = row.entry_snapshot if isinstance(row.entry_snapshot, dict) else {}
        candidate = dict(snap.get("candidate") or {})
        candidate.setdefault("symbol", symbol)
        candidate.setdefault("recommendation", row.recommendation)
        candidate.setdefault("score", row.scanner_score)
        candidate.setdefault("rank", row.scanner_rank)

        technical = {
            "ma5": row.ma5,
            "ma20": row.ma20,
            "rsi14": row.rsi14,
            "macd": row.macd,
            "atr14": row.atr14,
            "volume_surge": row.volume_surge,
            "trend": row.trend,
            "momentum": row.momentum,
            "volatility": row.volatility,
        }

        from stock_platform.operation.upbit_market_context.analysis_llm_service import (
            run_analysis_llm,
        )
        from stock_platform.operation.upbit_market_context.as_of import as_utc
        from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
            record_rag_cache_hit,
        )
        from stock_platform.operation.upbit_market_context.prompt_versions import (
            SCHEMA_RAG_V1,
        )
        from stock_platform.operation.upbit_market_context.rag_retrieval import (
            retrieve_similar_cases,
        )
        from stock_platform.operation.upbit_market_context.schemas import (
            fail_open_output,
        )
        from stock_platform.operation.upbit_market_context.source_registry import (
            QUALITY_AVAILABLE,
            QUALITY_STALE,
        )
        from stock_platform.operation.upbit_market_context.trading_llm_shadow import (
            run_trading_llm_shadow,
        )

        svc = MarketContextSnapshotService(session)
        inp, meta = svc.build_llm_input(
            detected_at=row.detected_at,
            candidate=candidate,
            technical=technical,
            news_items=None,
        )
        alignment = meta.get("alignment") if isinstance(meta, dict) else None
        lookahead_ok = True
        quality = QUALITY_AVAILABLE
        rag_result: dict[str, Any] = {
            "ok": False,
            "examples": [],
            "skipped": True,
            "reason": "LOOKAHEAD_OR_STALE",
        }
        if isinstance(alignment, dict) and alignment.get("ok") is False:
            heuristic = fail_open_output(reason="STALE_OR_LOOKAHEAD_CONTEXT")
            lookahead_ok = False
            quality = QUALITY_STALE
            analysis_result = {
                "ok": False,
                "fallback": True,
                "fallback_reason": "STALE_OR_LOOKAHEAD_CONTEXT",
                "model_role": "ANALYSIS",
            }
            trading_result = {
                "ok": False,
                "skipped": True,
                "reason": "LOOKAHEAD_OR_STALE",
                "mode": "SHADOW",
                "affects_real": False,
            }
        else:
            # 1) CURRENT heuristic — REAL/Scanner와 별도 연구 baseline
            heuristic = heuristic_llm_analyze(inp)
            # 2) ANALYSIS_LLM (cache) — Trading보다 먼저 요약 확보
            analysis_result = run_analysis_llm(inp, symbol=symbol)
            # 3) CLEAN RAG — Trading 입력용 과거 사례 (미래 outcome 금지)
            try:
                rag_result = retrieve_similar_cases(
                    session,
                    detected_at=row.detected_at,
                    technical=technical,
                    candidate=candidate,
                    analysis=analysis_result,
                    exclude_shadow_id=shadow_id,
                    market="UPBIT",
                )
                if rag_result.get("cache_hit"):
                    record_rag_cache_hit()
            except Exception as rag_exc:  # noqa: BLE001
                logger.warning(
                    "rag_retrieve_failed_open",
                    shadow_id=shadow_id,
                    error=type(rag_exc).__name__,
                )
                rag_result = {
                    "ok": False,
                    "examples": [],
                    "error": type(rag_exc).__name__,
                    "no_lookahead": True,
                    "clean_only": True,
                }
            # 4) TRADING_LLM SHADOW — priority gate로 동시 ANALYSIS보다 우선
            trading_result = run_trading_llm_shadow(
                inp,
                analysis_summary=analysis_result,
                heuristic=heuristic,
                rag_examples=list(rag_result.get("examples") or []),
            )

        # 저장 recommendation: heuristic 유지 (REAL 영향 없음).
        # Trading shadow는 output_json.trading_llm_shadow 에만 기록.
        detected = as_utc(row.detected_at) or row.detected_at
        out_payload = heuristic.model_dump()
        out_payload["schema_version"] = SCHEMA_RAG_V1
        out_payload["market"] = "UPBIT"
        out_payload["current_heuristic"] = heuristic.model_dump()
        out_payload["analysis_llm"] = analysis_result
        out_payload["rag"] = {
            "market": "UPBIT",
            "retrieval_method": rag_result.get("retrieval_method"),
            "top_k": rag_result.get("top_k"),
            "examples": rag_result.get("examples") or [],
            "cache_hit": bool(rag_result.get("cache_hit")),
            "no_lookahead": bool(rag_result.get("no_lookahead", True)),
            "clean_only": bool(rag_result.get("clean_only", True)),
            "eligible_scored": rag_result.get("eligible_scored"),
            "excluded": rag_result.get("excluded"),
            "cross_market_rag_count": int(rag_result.get("cross_market_rag_count") or 0),
        }
        out_payload["trading_llm_shadow"] = trading_result
        out_payload["comparison"] = {
            "heuristic_recommendation": heuristic.recommendation,
            "trading_shadow_recommendation": trading_result.get("recommendation"),
            "agree": (
                trading_result.get("ok")
                and trading_result.get("recommendation") == heuristic.recommendation
            ),
            "shadow_only": True,
            "real_policy_changed": False,
        }
        out_payload["latency_ms"] = {
            "analysis": analysis_result.get("latency_ms"),
            "trading_shadow": trading_result.get("latency_ms"),
        }

        # LlmContextOutput 필드는 heuristic 기준 — shadow가 REAL 컬럼을 덮지 않음
        from stock_platform.operation.upbit_market_context.schemas import LlmContextOutput

        stored = LlmContextOutput.model_validate(
            {
                **heuristic.model_dump(),
            }
        )
        ent = svc.save_llm_analysis(
            symbol=symbol,
            detected_at=detected,
            context_as_of=detected,
            inp=inp,
            out=stored,
            shadow_id=shadow_id,
            lookahead_ok=lookahead_ok,
            quality=quality,
        )
        # dual payload를 output_json에 merge (JSONB SoT)
        ent.output_json = out_payload
        # input에 role meta
        inp_dump = dict(ent.input_json or {})
        inp_dump["dual_llm"] = {
            "analysis_model": analysis_result.get("model"),
            "trading_model": trading_result.get("model"),
            "trading_mode": "SHADOW",
            "affects_real": False,
        }
        ent.input_json = inp_dump
        session.flush()
        return {
            "ok": True,
            "skipped": False,
            "analysis_id": int(ent.analysis_id),
            "heuristic_recommendation": heuristic.recommendation,
            "trading_shadow_recommendation": trading_result.get("recommendation"),
            "trading_shadow_ok": bool(trading_result.get("ok")),
            "analysis_ok": bool(analysis_result.get("ok")),
            "quality": quality,
            "trigger": "CANDIDATE_SHADOW_OPEN",
            "mode": "SHADOW",
            "live_order": False,
            "REAL_POLICY_CHANGED": "NO",
            "REAL_ORDER_MUTATION": 0,
            "LIVE_ARM_MUTATION": 0,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "candidate_llm_context_failed_open",
            shadow_id=getattr(row, "shadow_id", None),
            error=type(exc).__name__,
            detail=str(exc)[:160],
        )
        return {
            "ok": False,
            "research_failed_open": True,
            "error": type(exc).__name__,
            "live_order": False,
            "REAL_POLICY_CHANGED": "NO",
        }


# --- Shadow dual-LLM background (Scanner REAL path 비차단) ---
_SHADOW_LLM_MAX_QUEUE = 32
_shadow_llm_pending: set[int] = set()
_shadow_llm_queue: deque[int] = deque()
_shadow_llm_lock = threading.Lock()
_shadow_llm_worker_started = False


def shadow_llm_queue_stats() -> dict[str, Any]:
    with _shadow_llm_lock:
        return {
            "pending": len(_shadow_llm_pending),
            "queued": len(_shadow_llm_queue),
            "max_queue": _SHADOW_LLM_MAX_QUEUE,
        }


def schedule_shadow_candidate_llm(shadow_id: int) -> dict[str, Any]:
    """ALLOW Shadow 생성 후 dual LLM을 bounded background로 실행.

    Scanner completion을 await 하지 않음. 연구 실패는 REAL에 영향 없음.
    """

    global _shadow_llm_worker_started

    sid = int(shadow_id)
    if sid <= 0:
        return {"ok": False, "skipped": True, "reason": "INVALID_SHADOW_ID"}

    with _shadow_llm_lock:
        if sid in _shadow_llm_pending:
            return {
                "ok": True,
                "skipped": True,
                "reason": "DEDUP_INFLIGHT",
                "shadow_id": sid,
            }
        if len(_shadow_llm_pending) >= _SHADOW_LLM_MAX_QUEUE:
            return {
                "ok": False,
                "skipped": True,
                "reason": "QUEUE_FULL",
                "shadow_id": sid,
                "max_queue": _SHADOW_LLM_MAX_QUEUE,
            }
        _shadow_llm_pending.add(sid)
        _shadow_llm_queue.append(sid)
        start_worker = not _shadow_llm_worker_started
        if start_worker:
            _shadow_llm_worker_started = True

    if start_worker:
        try:
            threading.Thread(
                target=_shadow_llm_worker_loop,
                name="upbit-shadow-dual-llm",
                daemon=True,
            ).start()
        except Exception as exc:  # noqa: BLE001
            with _shadow_llm_lock:
                _shadow_llm_pending.discard(sid)
                _shadow_llm_worker_started = False
            logger.warning(
                "shadow_candidate_llm_schedule_failed",
                error=type(exc).__name__,
                shadow_id=sid,
            )
            return {
                "ok": False,
                "skipped": True,
                "reason": "THREAD_START_FAILED",
                "error": type(exc).__name__,
            }

    return {
        "ok": True,
        "skipped": False,
        "scheduled": True,
        "shadow_id": sid,
        "mode": "BACKGROUND_SHADOW",
        "affects_real": False,
    }


def _shadow_llm_worker_loop() -> None:
    """단일 worker — 무한 task 폭증 방지, queue drain."""

    global _shadow_llm_worker_started

    from stock_platform.database.session import get_session_factory

    SessionFactory = get_session_factory()
    while True:
        with _shadow_llm_lock:
            if not _shadow_llm_queue:
                _shadow_llm_worker_started = False
                return
            sid = _shadow_llm_queue.popleft()

        session = SessionFactory()
        try:
            row = session.get(UpbitOpportunityShadowEntity, sid)
            if row is None:
                logger.warning(
                    "shadow_candidate_llm_row_missing",
                    shadow_id=sid,
                )
            else:
                result = maybe_analyze_shadow_candidate(session, row)
                session.commit()
                logger.info(
                    "shadow_candidate_llm_background_done",
                    shadow_id=sid,
                    ok=result.get("ok"),
                    skipped=result.get("skipped"),
                    analysis_id=result.get("analysis_id"),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "shadow_candidate_llm_background_failed_open",
                shadow_id=sid,
                error=type(exc).__name__,
            )
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
        finally:
            session.close()
            with _shadow_llm_lock:
                _shadow_llm_pending.discard(sid)

