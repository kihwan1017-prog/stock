"""Selective Teacher LLM (qwen3.5:4b) — audit/reference only.

정답(ground truth)이 아니다. CLEAN actual outcome이 SoT.
TRADING보다 낮은 priority. Trading starvation 금지.
호출률 상한.
"""

from __future__ import annotations

import json
import random
import threading
from datetime import datetime, timezone
from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    ROLE_TEACHER,
    chat_json_sync,
    record_stat,
    teacher_config,
    teacher_enabled,
)
from stock_platform.operation.upbit_market_context.prompt_versions import (
    TEACHER_PROMPT_VERSION,
    settings_fingerprint,
)

TEACHER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "analysis_quality": {"type": "string"},
        "trading_decision_quality": {"type": "string"},
        "preferred_recommendation": {
            "type": "string",
            "enum": ["ALLOW", "HOLD", "REDUCE", "UNCERTAIN"],
        },
        "missed_risk_flags": {"type": "array", "items": {"type": "string"}},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "analysis_quality",
        "trading_decision_quality",
        "preferred_recommendation",
        "missed_risk_flags",
        "reason_codes",
    ],
}

SYSTEM_PROMPT = (
    "당신은 UPBIT 연구용 TEACHER_LLM(참조)입니다. "
    "Analysis/Trading 판단을 검토하지만 최종 정답을 결정하지 마세요. "
    "실제 outcome이 ground truth입니다. REAL 주문 금지. JSON만."
)

VALID_PREF = frozenset({"ALLOW", "HOLD", "REDUCE", "UNCERTAIN"})

_rate_lock = threading.Lock()
_teacher_calls = 0
_teacher_eligible = 0


def teacher_rate_stats() -> dict[str, Any]:
    with _rate_lock:
        return {
            "teacher_calls": _teacher_calls,
            "teacher_eligible_seen": _teacher_eligible,
            "review_rate": (
                round(_teacher_calls / _teacher_eligible, 4)
                if _teacher_eligible
                else None
            ),
        }


def _bump_eligible() -> None:
    global _teacher_eligible
    with _rate_lock:
        _teacher_eligible += 1


def _bump_call() -> None:
    global _teacher_calls
    with _rate_lock:
        _teacher_calls += 1


def should_call_teacher(
    *,
    analysis: dict[str, Any] | None,
    trading: dict[str, Any] | None,
    feedback: dict[str, Any] | None = None,
    parse_ok: bool = True,
) -> dict[str, Any]:
    """선택적 Teacher 트리거 + rate limit."""

    s = get_settings()
    max_rate = float(getattr(s, "teacher_llm_max_rate", 0.15) or 0.15)
    conf_th = float(getattr(s, "teacher_llm_confidence_threshold", 0.65) or 0.65)
    _bump_eligible()

    reasons: list[str] = []
    ana = analysis or {}
    tr = trading or {}
    fb = feedback or {}

    risks = [str(x).upper() for x in (ana.get("risk_factors") or [])]
    tone = str(ana.get("tone") or "").upper()
    risk_high = tone in {"BEARISH", "CAUTION"} or any(
        "HIGH" in x or x in {"MARKET_WEAK", "NEWS_NEGATIVE"} for x in risks
    )
    rec = str(tr.get("recommendation") or "").upper()
    try:
        conf = float(tr.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0

    # A: Analysis HIGH risk vs Trading ALLOW high confidence
    if risk_high and rec == "ALLOW" and conf >= conf_th:
        reasons.append("ANALYSIS_TRADING_CONFLICT")
    # B: low confidence
    if tr.get("ok") and conf < conf_th:
        reasons.append("LOW_CONFIDENCE")
    # C: ALLOW 후 EARLY_DUMP
    verd = str(fb.get("prediction_verdict") or "")
    if verd == "ALLOW_EARLY_DUMP":
        reasons.append("ALLOW_EARLY_DUMP")
    # D: HOLD/REDUCE 후 big winner
    if verd in {"HOLD_MISSED_WINNER", "REDUCE_MISSED_WINNER"}:
        reasons.append("MISSED_WINNER")
    # E: parse/quality
    if not parse_ok or (tr and not tr.get("ok") and not tr.get("skipped")):
        reasons.append("PARSE_OR_QUALITY")
    # F: research sampling
    sample_rate = float(getattr(s, "teacher_llm_sample_rate", 0.05) or 0.05)
    if random.random() < sample_rate:
        reasons.append("RESEARCH_SAMPLE")

    if not reasons:
        return {"trigger": False, "reasons": [], "deferred": False}

    # rate limit — 이미 상한 초과면 defer
    with _rate_lock:
        rate = (_teacher_calls / _teacher_eligible) if _teacher_eligible else 0.0
    if rate >= max_rate and "RESEARCH_SAMPLE" in reasons and len(reasons) == 1:
        return {
            "trigger": False,
            "reasons": reasons,
            "deferred": True,
            "defer_reason": "MAX_RATE",
        }
    if rate >= max_rate and not any(
        r in reasons
        for r in (
            "ANALYSIS_TRADING_CONFLICT",
            "ALLOW_EARLY_DUMP",
            "MISSED_WINNER",
            "PARSE_OR_QUALITY",
        )
    ):
        return {
            "trigger": False,
            "reasons": reasons,
            "deferred": True,
            "defer_reason": "MAX_RATE",
        }

    return {"trigger": True, "reasons": reasons, "deferred": False}


def run_teacher_review(
    *,
    analysis: dict[str, Any] | None,
    trading: dict[str, Any] | None,
    rag_examples: list[dict[str, Any]] | None = None,
    feedback: dict[str, Any] | None = None,
    trigger_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Teacher 호출 — Trading을 대기시키지 않음(호출측에서 post-hoc)."""

    base = {
        "teacher_model": teacher_config().model,
        "model_role": ROLE_TEACHER,
        "prompt_version": TEACHER_PROMPT_VERSION,
        "is_ground_truth": False,
        "affects_real": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trigger_reasons": list(trigger_reasons or []),
    }
    if not teacher_enabled():
        return {**base, "ok": False, "skipped": True, "reason": "TEACHER_DISABLED"}

    cfg = teacher_config()
    compact = {
        "analysis": {
            "tone": (analysis or {}).get("tone"),
            "risk_factors": (analysis or {}).get("risk_factors"),
            "confidence": (analysis or {}).get("confidence"),
            "market_summary": str((analysis or {}).get("market_summary") or "")[:200],
        },
        "trading_shadow": {
            "recommendation": (trading or {}).get("recommendation"),
            "confidence": (trading or {}).get("confidence"),
            "early_dump_risk": (trading or {}).get("early_dump_risk"),
            "fee_churn_risk": (trading or {}).get("fee_churn_risk"),
            "reason_codes": (trading or {}).get("reason_codes"),
        },
        "rag_examples_compact": [
            {
                "case_id": e.get("case_id"),
                "similarity_score": e.get("similarity_score"),
                "actual_label": e.get("actual_label"),
            }
            for e in (rag_examples or [])[:3]
        ],
        "feedback_verdict": (feedback or {}).get("prediction_verdict"),
        "note": "Teacher는 정답이 아님. actual outcome이 SoT.",
    }
    raw = chat_json_sync(
        config=cfg,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            "Analysis/Trading 품질을 검토하세요. preferred는 참고 의견입니다.\n"
            + json.dumps(compact, ensure_ascii=False, default=str)
        ),
        response_schema=TEACHER_SCHEMA,
    )
    _bump_call()
    record_stat(
        ROLE_TEACHER,
        ok=bool(raw.get("ok")),
        timeout=bool(raw.get("timeout")),
        latency_ms=raw.get("latency_ms"),
    )
    if not raw.get("ok") or not isinstance(raw.get("parsed"), dict):
        return {
            **base,
            "ok": False,
            "timeout": bool(raw.get("timeout")),
            "error": raw.get("error"),
            "latency_ms": raw.get("latency_ms"),
            "settings_fingerprint": settings_fingerprint(
                model=cfg.model,
                role=ROLE_TEACHER,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                prompt_version=TEACHER_PROMPT_VERSION,
            ),
        }

    p = raw["parsed"]
    pref = str(p.get("preferred_recommendation") or "UNCERTAIN").upper()
    if pref not in VALID_PREF:
        pref = "UNCERTAIN"
    return {
        **base,
        "ok": True,
        "review": {
            "analysis_quality": str(p.get("analysis_quality") or "")[:200],
            "trading_decision_quality": str(p.get("trading_decision_quality") or "")[
                :200
            ],
            "preferred_recommendation": pref,
            "missed_risk_flags": [
                str(x).upper()[:40] for x in (p.get("missed_risk_flags") or [])[:10]
            ],
            "reason_codes": [str(x)[:40] for x in (p.get("reason_codes") or [])[:10]],
        },
        "latency_ms": raw.get("latency_ms"),
        "settings_fingerprint": settings_fingerprint(
            model=cfg.model,
            role=ROLE_TEACHER,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            prompt_version=TEACHER_PROMPT_VERSION,
        ),
    }
