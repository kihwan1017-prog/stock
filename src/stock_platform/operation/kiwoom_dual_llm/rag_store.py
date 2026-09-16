"""KIWOOM CLEAN RAG retrieval — reuses hybrid similarity, KIWOOM-only corpus."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.dual_llm.markets import MARKET_KIWOOM, require_market
from stock_platform.operation.kiwoom_dual_llm.clean_research import (
    classify_kiwoom_research_row,
)
from stock_platform.operation.upbit_market_context.as_of import as_utc
from stock_platform.operation.upbit_market_context.entities import (
    UpbitLlmContextAnalysisEntity,
)
from stock_platform.operation.upbit_market_context.rag_retrieval import (
    candidate_feature_vector,
    rag_cache,
    similarity_score,
)


def _case_from_analysis(ent: UpbitLlmContextAnalysisEntity) -> dict[str, Any] | None:
    inp = ent.input_json if isinstance(ent.input_json, dict) else {}
    out = ent.output_json if isinstance(ent.output_json, dict) else {}
    cls = classify_kiwoom_research_row(input_json=inp, output_json=out)
    if not cls.get("clean"):
        return None
    fb = out.get("feedback") if isinstance(out.get("feedback"), dict) else {}
    outcome = fb.get("actual_outcome") if isinstance(fb.get("actual_outcome"), dict) else {}
    if not outcome or outcome.get("label") in {None, "INSUFFICIENT_DATA"}:
        return None
    completed_at = outcome.get("completed_at") or out.get("outcome_completed_at")
    if not completed_at:
        return None
    tech = inp.get("technical") if isinstance(inp.get("technical"), dict) else {}
    analysis = out.get("analysis_llm") if isinstance(out.get("analysis_llm"), dict) else {}
    return {
        "case_id": f"kiwoom_analysis:{int(ent.analysis_id)}",
        "market": MARKET_KIWOOM,
        "analysis_id": int(ent.analysis_id),
        "symbol": ent.symbol,
        "detected_at": (
            ent.detected_at.isoformat() if ent.detected_at else None
        ),
        "outcome_completed_at": completed_at,
        "clean": True,
        "entry_context": {
            "rsi": tech.get("rsi14"),
            "ma_separation_pct": tech.get("ma_separation_pct"),
            "volume_ratio": tech.get("volume_ratio"),
            "scanner_score": (inp.get("candidate") or {}).get("score")
            if isinstance(inp.get("candidate"), dict)
            else None,
            "analysis_risk_flags": analysis.get("risk_flags") or [],
            "news_state": analysis.get("news_state"),
            "disclosure_state": analysis.get("disclosure_state"),
            "market_state": analysis.get("market_state"),
        },
        "outcome": outcome,
    }


def retrieve_kiwoom_similar_cases(
    session: Session,
    *,
    detected_at: datetime,
    technical: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    analysis: dict[str, Any] | None = None,
    top_k: int | None = None,
    exclude_analysis_id: int | None = None,
    market: str = MARKET_KIWOOM,
) -> dict[str, Any]:
    market_n = require_market(market)
    if market_n != MARKET_KIWOOM:
        return {
            "ok": True,
            "market": market_n,
            "examples": [],
            "cross_market_rag_count": 0,
            "excluded": {"cross_market_blocked": 1},
            "no_lookahead": True,
            "clean_only": True,
        }

    s = get_settings()
    k = int(top_k if top_k is not None else getattr(s, "dual_llm_rag_top_k", 5) or 5)
    k = max(1, min(10, k))
    ttl = float(getattr(s, "dual_llm_rag_cache_ttl_seconds", 300.0) or 300.0)
    det = as_utc(detected_at) or detected_at
    if det.tzinfo is None:
        det = det.replace(tzinfo=timezone.utc)

    query = candidate_feature_vector(
        technical=technical, candidate=candidate, analysis=analysis
    )
    # market-isolated cache key via UPBIT helper pattern
    from stock_platform.operation.upbit_market_context.rag_retrieval import _cache_key

    ck = _cache_key(query, detected_at=det, market=market_n)
    cached = rag_cache.get(ck)
    if cached is not None:
        examples = [
            e
            for e in (cached.get("examples") or [])
            if e.get("market") == MARKET_KIWOOM
        ][:k]
        return {
            **cached,
            "market": MARKET_KIWOOM,
            "examples": examples,
            "cache_hit": True,
            "cross_market_rag_count": 0,
        }

    rows = list(
        session.scalars(
            select(UpbitLlmContextAnalysisEntity)
            .order_by(desc(UpbitLlmContextAnalysisEntity.created_at))
            .limit(800)
        )
    )
    scored: list[tuple[float, dict[str, Any]]] = []
    excluded = {
        "not_kiwoom_or_not_clean": 0,
        "lookahead": 0,
        "self": 0,
        "cross_market": 0,
    }
    for ent in rows:
        if exclude_analysis_id is not None and int(ent.analysis_id) == int(
            exclude_analysis_id
        ):
            excluded["self"] += 1
            continue
        inp = ent.input_json if isinstance(ent.input_json, dict) else {}
        if (inp.get("market") or "").upper() not in {MARKET_KIWOOM, "KRX"}:
            excluded["cross_market"] += 1
            continue
        doc = _case_from_analysis(ent)
        if doc is None:
            excluded["not_kiwoom_or_not_clean"] += 1
            continue
        completed_s = doc.get("outcome_completed_at")
        try:
            completed = as_utc(
                datetime.fromisoformat(str(completed_s).replace("Z", "+00:00"))
            )
        except ValueError:
            excluded["lookahead"] += 1
            continue
        if completed is None or completed >= det:
            excluded["lookahead"] += 1
            continue
        sim = similarity_score(query, doc)
        scored.append(
            (
                sim,
                {
                    "case_id": doc["case_id"],
                    "market": MARKET_KIWOOM,
                    "analysis_id": doc.get("analysis_id"),
                    "symbol": doc["symbol"],
                    "similarity_score": sim,
                    "entry_summary": {
                        "rsi": (doc["entry_context"] or {}).get("rsi"),
                        "ma_separation_pct": (doc["entry_context"] or {}).get(
                            "ma_separation_pct"
                        ),
                        "volume_ratio": (doc["entry_context"] or {}).get(
                            "volume_ratio"
                        ),
                        "scanner_score": (doc["entry_context"] or {}).get(
                            "scanner_score"
                        ),
                    },
                    "actual_label": (doc["outcome"] or {}).get("label"),
                    "mfe": (doc["outcome"] or {}).get("mfe"),
                    "mae": (doc["outcome"] or {}).get("mae"),
                    "outcome_completed_at": completed_s,
                },
            )
        )

    scored.sort(key=lambda x: (-x[0], x[1].get("analysis_id") or 0))
    examples = [e for _, e in scored[:k]]
    payload = {
        "ok": True,
        "market": MARKET_KIWOOM,
        "retrieval_method": "structured_hybrid_normalized_distance",
        "top_k": k,
        "pool_scanned": len(rows),
        "eligible_scored": len(scored),
        "excluded": excluded,
        "examples": examples,
        "no_lookahead": True,
        "clean_only": True,
        "cache_hit": False,
        "cross_market_rag_count": int(excluded["cross_market"]),
        "as_of": det.isoformat(),
    }
    rag_cache.put(ck, {**payload, "cache_hit": False}, ttl_seconds=ttl)
    return payload
