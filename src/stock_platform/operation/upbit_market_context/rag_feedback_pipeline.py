"""RAG + Feedback pipeline applicator — CLEAN outcome 완료 시 JSONB enrich.

기존 CLEAN outcome / Legacy / Backfill 수정 금지.
prediction/feedback/dataset provenance만 추가.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.operation.upbit_market_context.entities import (
    UpbitLlmContextAnalysisEntity,
)
from stock_platform.operation.upbit_market_context.feedback_scoring import (
    build_feedback_payload,
)
from stock_platform.operation.upbit_market_context.learning_dataset import (
    build_learning_example,
)
from stock_platform.operation.upbit_market_context.prompt_versions import (
    ANALYSIS_PROMPT_VERSION,
    SCHEMA_RAG_V1,
    TEACHER_PROMPT_VERSION,
    TRADING_PROMPT_VERSION,
    is_dual_llm_schema,
)
from stock_platform.operation.upbit_market_context.teacher_llm import (
    run_teacher_review,
    should_call_teacher,
)
from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    COHORT_CLEAN_FORWARD,
    classify_forward_row,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
    build_forward_obs,
)


def apply_feedback_for_shadow(
    session: Session,
    row: UpbitOpportunityShadowEntity,
    *,
    run_teacher: bool = True,
) -> dict[str, Any]:
    """COMPLETED shadow에 연결된 dual-llm analysis row에 feedback 기록."""

    sid = int(row.shadow_id)
    cls = classify_forward_row(row)
    analyses = list(
        session.scalars(
            select(UpbitLlmContextAnalysisEntity).where(
                UpbitLlmContextAnalysisEntity.shadow_id == sid
            )
        )
    )
    if not analyses:
        return {"ok": False, "reason": "NO_ANALYSIS_ROW", "shadow_id": sid}

    updated = 0
    for ent in analyses:
        out = dict(ent.output_json) if isinstance(ent.output_json, dict) else {}
        if not is_dual_llm_schema(out.get("schema_version")):
            continue
        # 이미 feedback 있으면 덮어쓰지 않음 (기존 outcome 수정 금지 정신)
        if isinstance(out.get("feedback"), dict) and out["feedback"].get(
            "prediction_verdict"
        ):
            continue

        trading = (
            out.get("trading_llm_shadow")
            if isinstance(out.get("trading_llm_shadow"), dict)
            else {}
        )
        analysis = (
            out.get("analysis_llm") if isinstance(out.get("analysis_llm"), dict) else {}
        )
        heur = (
            out.get("current_heuristic")
            if isinstance(out.get("current_heuristic"), dict)
            else {}
        )
        rag = out.get("rag") if isinstance(out.get("rag"), dict) else {}

        obs = None
        if cls.get("clean"):
            obs = build_forward_obs(row, cohort=COHORT_CLEAN_FORWARD)

        feedback = build_feedback_payload(
            trading_prediction=trading,
            heuristic=heur,
            analysis=analysis,
            obs=obs,
            row=row,
        )

        teacher_block: dict[str, Any] | None = None
        if run_teacher:
            decide = should_call_teacher(
                analysis=analysis,
                trading=trading,
                feedback=feedback,
                parse_ok=bool(trading.get("ok")),
            )
            if decide.get("trigger"):
                try:
                    teacher_block = run_teacher_review(
                        analysis=analysis,
                        trading=trading,
                        rag_examples=rag.get("examples") or [],
                        feedback=feedback,
                        trigger_reasons=list(decide.get("reasons") or []),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "teacher_review_failed_open",
                        shadow_id=sid,
                        error=type(exc).__name__,
                    )
                    teacher_block = {
                        "ok": False,
                        "error": type(exc).__name__,
                        "is_ground_truth": False,
                    }
            else:
                teacher_block = {
                    "ok": False,
                    "skipped": True,
                    "trigger": False,
                    "reasons": decide.get("reasons") or [],
                    "deferred": bool(decide.get("deferred")),
                    "is_ground_truth": False,
                }

        quality = {
            "clean": bool(cls.get("clean")),
            "no_lookahead": True,
            "canonical_price": "INVALID_PRICE_SOURCE"
            not in (cls.get("exclusions") or []),
            "outcome_complete": getattr(row, "return_5m_pct", None) is not None,
            "prediction_parse_valid": bool(trading.get("ok")),
            "context_full": bool(analysis.get("ok")) and bool(rag.get("examples")),
            "legacy": cls.get("cohort") == "LEGACY",
            "backfill": "BACKFILL" in str(cls.get("cohort") or ""),
            "contaminated": False,
        }
        learning = build_learning_example(
            input_snapshot={
                "shadow_id": sid,
                "symbol": row.symbol,
                "detected_at": (
                    row.detected_at.isoformat() if row.detected_at else None
                ),
                "technical": (ent.input_json or {}).get("technical")
                if isinstance(ent.input_json, dict)
                else None,
                "candidate": (ent.input_json or {}).get("candidate")
                if isinstance(ent.input_json, dict)
                else None,
            },
            rag_context=rag,
            analysis_prediction=analysis,
            trading_prediction=trading,
            teacher_review=teacher_block,
            feedback=feedback,
            quality=quality,
            prompt_versions={
                "analysis": analysis.get("prompt_version") or ANALYSIS_PROMPT_VERSION,
                "trading": trading.get("prompt_version") or TRADING_PROMPT_VERSION,
                "teacher": TEACHER_PROMPT_VERSION,
            },
            model_versions={
                "analysis": analysis.get("model"),
                "trading": trading.get("model"),
                "teacher": (teacher_block or {}).get("teacher_model"),
            },
        )

        out["schema_version"] = SCHEMA_RAG_V1
        out["feedback"] = feedback
        out["teacher_review"] = teacher_block
        out["learning_example"] = learning
        out["dataset_tier"] = learning.get("dataset_tier")
        ent.output_json = out
        updated += 1

    if updated:
        session.flush()
    return {
        "ok": True,
        "shadow_id": sid,
        "updated": updated,
        "clean": bool(cls.get("clean")),
    }
