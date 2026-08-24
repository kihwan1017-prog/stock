"""Candidate-driven LLM context analysis — research only, fail-open.

Scanner 신규 Shadow 생성 시에만 실행. 전종목 주기 LLM 호출 금지.
REAL 주문/정책을 차단하거나 변경하지 않는다.
"""

from __future__ import annotations

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
    """단일 Shadow 후보에 대해 heuristic LLM context 저장.

    실패해도 raise하지 않음 (research_failed_open).
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

        from stock_platform.operation.upbit_market_context.as_of import as_utc
        from stock_platform.operation.upbit_market_context.schemas import (
            fail_open_output,
        )
        from stock_platform.operation.upbit_market_context.source_registry import (
            QUALITY_AVAILABLE,
            QUALITY_STALE,
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
        # freshness / lookahead gate — fail-open HOLD (REAL block 금지)
        if isinstance(alignment, dict) and alignment.get("ok") is False:
            out = fail_open_output(reason="STALE_OR_LOOKAHEAD_CONTEXT")
            lookahead_ok = False
            quality = QUALITY_STALE
        else:
            out = heuristic_llm_analyze(inp)

        detected = as_utc(row.detected_at) or row.detected_at
        ent = svc.save_llm_analysis(
            symbol=symbol,
            detected_at=detected,
            context_as_of=detected,
            inp=inp,
            out=out,
            shadow_id=shadow_id,
            lookahead_ok=lookahead_ok,
            quality=quality,
        )
        session.flush()
        return {
            "ok": True,
            "skipped": False,
            "analysis_id": int(ent.analysis_id),
            "recommendation": out.recommendation,
            "quality": quality,
            "trigger": "CANDIDATE_SHADOW_OPEN",
            "live_order": False,
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
