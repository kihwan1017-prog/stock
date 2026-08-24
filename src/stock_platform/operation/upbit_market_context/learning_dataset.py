"""Learning example + dataset tier + LoRA export prep (학습 자체는 수행 안 함)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from stock_platform.operation.upbit_opportunity_shadow.entry_quality_early_dump_experiment import (
    N_COLLECTION,
    N_PRIMARY,
    N_RECOMMENDED,
)

TIER_GOLD = "GOLD"
TIER_SILVER = "SILVER"
TIER_EXCLUDED = "EXCLUDED"

STAGE_COLLECTION = "COLLECTION_ONLY"
STAGE_DIAGNOSTIC = "DIAGNOSTIC"
STAGE_PRIMARY = "PRIMARY_REVIEW"
STAGE_LORA_READY = "LORA_DATASET_REVIEW_READY"


def sample_stage(clean_n: int) -> dict[str, Any]:
    """CLEAN count → LoRA dataset readiness stage (자동 학습 금지)."""

    n = int(clean_n or 0)
    if n < N_COLLECTION:
        stage = STAGE_COLLECTION
    elif n < N_PRIMARY:
        stage = STAGE_DIAGNOSTIC
    elif n < N_RECOMMENDED:
        stage = STAGE_PRIMARY
    else:
        stage = STAGE_LORA_READY
    return {
        "CLEAN_SAMPLE_COUNT": n,
        "SAMPLE_STAGE": stage,
        "LORA_TRAINING_STARTED": False,
        "auto_lora_forbidden": True,
        "thresholds": {
            "collection": N_COLLECTION,
            "diagnostic": N_COLLECTION,
            "primary": N_PRIMARY,
            "lora_review": N_RECOMMENDED,
        },
    }


def assign_dataset_tier(
    *,
    clean: bool,
    no_lookahead: bool,
    canonical_price: bool,
    outcome_complete: bool,
    prediction_parse_valid: bool,
    context_full: bool,
    legacy: bool = False,
    backfill: bool = False,
    contaminated: bool = False,
) -> str:
    if (
        legacy
        or backfill
        or contaminated
        or not clean
        or not no_lookahead
        or not canonical_price
        or not outcome_complete
    ):
        return TIER_EXCLUDED
    if prediction_parse_valid and context_full:
        return TIER_GOLD
    if outcome_complete and clean:
        return TIER_SILVER
    return TIER_EXCLUDED


def build_learning_example(
    *,
    input_snapshot: dict[str, Any],
    rag_context: dict[str, Any] | None,
    analysis_prediction: dict[str, Any] | None,
    trading_prediction: dict[str, Any] | None,
    teacher_review: dict[str, Any] | None,
    feedback: dict[str, Any] | None,
    quality: dict[str, Any],
    prompt_versions: dict[str, str],
    model_versions: dict[str, str],
    split_hint: str | None = None,
) -> dict[str, Any]:
    tier = assign_dataset_tier(
        clean=bool(quality.get("clean")),
        no_lookahead=bool(quality.get("no_lookahead")),
        canonical_price=bool(quality.get("canonical_price")),
        outcome_complete=bool(quality.get("outcome_complete")),
        prediction_parse_valid=bool(quality.get("prediction_parse_valid")),
        context_full=bool(quality.get("context_full")),
        legacy=bool(quality.get("legacy")),
        backfill=bool(quality.get("backfill")),
        contaminated=bool(quality.get("contaminated")),
    )
    return {
        "schema": "dual_llm_learning_example_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_snapshot": input_snapshot,
        "rag_context": rag_context,
        "analysis_prediction": analysis_prediction,
        "trading_prediction": trading_prediction,
        "teacher_review": teacher_review,
        "actual_outcome": (feedback or {}).get("actual_outcome"),
        "feedback": feedback,
        "quality": {**quality, "tier": tier},
        "dataset_tier": tier,
        "prompt_versions": prompt_versions,
        "model_versions": model_versions,
        "split": {
            "suggested": split_hint or "UNASSIGNED",
            "method": "time_ordered_ready",
            "note": "random row split 금지 — 시간순 TRAIN/VAL/TEST 준비만",
        },
        "lora_ready": tier == TIER_GOLD,
    }


def assign_time_splits(
    examples: list[dict[str, Any]],
    *,
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
) -> list[dict[str, Any]]:
    """시간순 split metadata만 부여 (학습 실행 없음)."""

    ordered = sorted(
        examples,
        key=lambda e: str(
            ((e.get("input_snapshot") or {}).get("detected_at"))
            or e.get("created_at")
            or ""
        ),
    )
    n = len(ordered)
    if n == 0:
        return ordered
    t_end = int(n * train_ratio)
    v_end = int(n * (train_ratio + val_ratio))
    out: list[dict[str, Any]] = []
    for i, ex in enumerate(ordered):
        if i < t_end:
            split = "TRAIN"
        elif i < v_end:
            split = "VALIDATION"
        else:
            split = "TEST"
        cloned = dict(ex)
        cloned["split"] = {
            **(ex.get("split") or {}),
            "suggested": split,
            "method": "time_ordered",
            "index": i,
            "n": n,
        }
        out.append(cloned)
    return out


def export_jsonl_rows(
    examples: Iterable[dict[str, Any]],
    *,
    kind: str,
    clean_n: int,
) -> dict[str, Any]:
    """READ-ONLY export prep — N 부족 시 RESEARCH_EXPORT_ONLY."""

    stage = sample_stage(clean_n)
    rows: list[str] = []
    gold = silver = excluded = 0
    for ex in examples:
        tier = str(ex.get("dataset_tier") or TIER_EXCLUDED)
        if tier == TIER_GOLD:
            gold += 1
        elif tier == TIER_SILVER:
            silver += 1
        else:
            excluded += 1
            continue
        if kind == "analysis":
            payload = {
                "input": ex.get("input_snapshot"),
                "output": {
                    "market_summary": (ex.get("analysis_prediction") or {}).get(
                        "market_summary"
                    ),
                    "asset_summary": (ex.get("analysis_prediction") or {}).get(
                        "asset_summary"
                    ),
                    "news_summary": (ex.get("analysis_prediction") or {}).get(
                        "news_summary"
                    ),
                    "risk_factors": (ex.get("analysis_prediction") or {}).get(
                        "risk_factors"
                    ),
                    "tone": (ex.get("analysis_prediction") or {}).get("tone"),
                },
                "tier": tier,
                "split": (ex.get("split") or {}).get("suggested"),
            }
        elif kind == "trading":
            # Analysis dataset과 섞지 않음
            payload = {
                "input": {
                    "technical": (ex.get("input_snapshot") or {}).get("technical"),
                    "analysis_summary": {
                        "tone": (ex.get("analysis_prediction") or {}).get("tone"),
                        "risk_factors": (ex.get("analysis_prediction") or {}).get(
                            "risk_factors"
                        ),
                    },
                    "rag_examples": (ex.get("rag_context") or {}).get("examples"),
                },
                "output": {
                    "recommendation": (ex.get("trading_prediction") or {}).get(
                        "recommendation"
                    ),
                    "entry_quality_score": (ex.get("trading_prediction") or {}).get(
                        "entry_quality_score"
                    ),
                    "early_dump_risk": (ex.get("trading_prediction") or {}).get(
                        "early_dump_risk"
                    ),
                    "fee_churn_risk": (ex.get("trading_prediction") or {}).get(
                        "fee_churn_risk"
                    ),
                    "reason_codes": (ex.get("trading_prediction") or {}).get(
                        "reason_codes"
                    ),
                },
                "tier": tier,
                "split": (ex.get("split") or {}).get("suggested"),
                # leakage 방지: 현재 후보 미래 outcome 미포함
                "no_current_future_outcome": True,
            }
        else:
            continue
        rows.append(json.dumps(payload, ensure_ascii=False, default=str))

    export_mode = (
        "RESEARCH_EXPORT_ONLY"
        if stage["SAMPLE_STAGE"] != STAGE_LORA_READY
        else "LORA_REVIEW_EXPORT"
    )
    return {
        "kind": kind,
        "line_count": len(rows),
        "GOLD": gold,
        "SILVER": silver,
        "EXCLUDED": excluded,
        "export_mode": export_mode,
        "LORA_TRAINING_STARTED": False,
        "apply_to_ops_forbidden": True,
        "lines": rows,
        **stage,
    }
