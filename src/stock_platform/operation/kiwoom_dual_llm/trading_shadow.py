"""KIWOOM TRADING_LLM SHADOW — Entry Quality (qwen3.5:2b). REAL 미배선."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from stock_platform.operation.dual_llm.markets import MARKET_KIWOOM
from stock_platform.operation.dual_llm.prompt_versions import (
    TRADING_KIWOOM_PROMPT_V1,
    settings_fingerprint,
)
from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    ROLE_TRADING,
    chat_json_sync,
    dual_llm_enabled,
    record_stat,
    trading_config,
    trading_shadow_enabled,
)

TRADING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "recommendation": {
            "type": "string",
            "enum": ["ALLOW", "HOLD", "REDUCE"],
        },
        "entry_quality_score": {"type": "integer"},
        "early_dump_risk": {
            "type": "string",
            "enum": ["LOW", "MEDIUM", "HIGH"],
        },
        "fee_churn_risk": {
            "type": "string",
            "enum": ["LOW", "MEDIUM", "HIGH"],
        },
        "event_risk": {
            "type": "string",
            "enum": ["LOW", "MEDIUM", "HIGH"],
        },
        "confidence": {"type": "number"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
        "reason_ko": {"type": "string"},
    },
    "required": [
        "recommendation",
        "entry_quality_score",
        "early_dump_risk",
        "fee_churn_risk",
        "event_risk",
        "confidence",
        "risk_flags",
        "reason_codes",
    ],
}

SYSTEM_PROMPT = (
    "당신은 KIWOOM(KRX) TRADING_LLM SHADOW입니다. "
    "ALLOW|HOLD|REDUCE 보조판단만 합니다. REAL 주문을 만들지 마세요. "
    "기술지표·분석·공시/뉴스·과거 KIWOOM CLEAN RAG만 사용하세요. "
    "현재 후보의 미래 결과는 모릅니다. JSON만."
)

VALID_REC = frozenset({"ALLOW", "HOLD", "REDUCE"})
VALID_RISK = frozenset({"LOW", "MEDIUM", "HIGH"})


def run_kiwoom_trading_llm_shadow(
    ctx: dict[str, Any],
    *,
    analysis_summary: dict[str, Any] | None,
    rag_examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cfg = trading_config()
    base = {
        "market": MARKET_KIWOOM,
        "model_role": ROLE_TRADING,
        "mode": "SHADOW",
        "prompt_version": TRADING_KIWOOM_PROMPT_V1,
        "model_name": cfg.model,
        "settings_fingerprint": settings_fingerprint(
            model=cfg.model,
            role=ROLE_TRADING,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            prompt_version=TRADING_KIWOOM_PROMPT_V1,
            market=MARKET_KIWOOM,
        ),
        "affects_real": False,
        "affects_live_arm": False,
        "affects_ma_evaluator": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if not dual_llm_enabled() or not trading_shadow_enabled():
        return {
            **base,
            "ok": False,
            "skipped": True,
            "reason": "TRADING_SHADOW_DISABLED",
            "model": cfg.model,
        }

    analysis = analysis_summary or {}
    compact = {
        "market": MARKET_KIWOOM,
        "candidate": ctx.get("candidate"),
        "technical": ctx.get("technical"),
        "analysis": {
            "market_state": analysis.get("market_state"),
            "asset_state": analysis.get("asset_state"),
            "news_state": analysis.get("news_state"),
            "disclosure_state": analysis.get("disclosure_state"),
            "risk_level": analysis.get("risk_level"),
            "risk_flags": analysis.get("risk_flags"),
            "summary_ko": analysis.get("summary_ko"),
            "confidence": analysis.get("confidence"),
        },
        "rag_examples": [
            {
                "case_id": e.get("case_id"),
                "market": e.get("market"),
                "similarity_score": e.get("similarity_score"),
                "entry_summary": e.get("entry_summary"),
                "actual_label": e.get("actual_label"),
                "mfe": e.get("mfe"),
                "mae": e.get("mae"),
            }
            for e in (rag_examples or [])[:5]
            if e.get("market", MARKET_KIWOOM) == MARKET_KIWOOM
        ],
        "research_only": True,
        "shadow_only": True,
        "lookahead_forbidden": True,
        "current_future_outcome_forbidden": True,
    }
    raw = chat_json_sync(
        config=cfg,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            "KIWOOM Entry Quality / Early Dump / Fee Churn / Event Risk를 "
            "SHADOW로 평가하세요.\n"
            + json.dumps(compact, ensure_ascii=False, default=str)
        ),
        response_schema=TRADING_SCHEMA,
    )
    record_stat(
        ROLE_TRADING,
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
            "model": cfg.model,
            "fallback_to_heuristic": True,
            "rag_example_count": len(compact["rag_examples"]),
        }

    p = raw["parsed"]
    rec = str(p.get("recommendation") or "").upper()
    if rec not in VALID_REC:
        return {
            **base,
            "ok": False,
            "error": f"INVALID_RECOMMENDATION:{rec}",
            "model": cfg.model,
            "fallback_to_heuristic": True,
        }

    def _risk(key: str) -> str:
        v = str(p.get(key) or "MEDIUM").upper()
        return v if v in VALID_RISK else "MEDIUM"

    try:
        score = max(0, min(100, int(p.get("entry_quality_score"))))
    except (TypeError, ValueError):
        score = 50
    try:
        conf = max(0.0, min(1.0, float(p.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        conf = 0.0

    return {
        **base,
        "ok": True,
        "model": cfg.model,
        "recommendation": rec,
        "entry_quality_score": score,
        "early_dump_risk": _risk("early_dump_risk"),
        "fee_churn_risk": _risk("fee_churn_risk"),
        "event_risk": _risk("event_risk"),
        "confidence": conf,
        "risk_flags": [str(x).upper()[:40] for x in (p.get("risk_flags") or [])[:10]],
        "reason_codes": [str(x)[:40] for x in (p.get("reason_codes") or [])[:10]],
        "reason_ko": str(p.get("reason_ko") or "")[:240],
        "latency_ms": raw.get("latency_ms"),
        "fallback_to_heuristic": False,
        "rag_example_count": len(compact["rag_examples"]),
    }
