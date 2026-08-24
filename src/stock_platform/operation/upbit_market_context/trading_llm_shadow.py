"""TRADING_LLM SHADOW — Entry Quality / Early Dump (qwen3.5:2b).

결과는 SHADOW ONLY. REAL candidate/slot/order/risk/LIVE/ARM에 영향 금지.
timeout/error 시 호출측이 heuristic을 유지한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    ROLE_TRADING,
    chat_json_sync,
    dual_llm_enabled,
    record_stat,
    trading_config,
    trading_shadow_enabled,
)
from stock_platform.operation.upbit_market_context.schemas import (
    LlmContextInput,
    LlmContextOutput,
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
        "confidence": {"type": "number"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
        "short_reason_ko": {"type": "string"},
    },
    "required": [
        "recommendation",
        "entry_quality_score",
        "early_dump_risk",
        "confidence",
        "risk_flags",
        "reason_codes",
    ],
}

SYSTEM_PROMPT = (
    "당신은 UPBIT TRADING_LLM SHADOW입니다. "
    "ALLOW|HOLD|REDUCE 보조판단만 합니다. REAL 주문을 만들지 마세요. "
    "미래 수익률은 모릅니다. Analysis 요약과 기술지표만 사용하세요. JSON만."
)

VALID_REC = frozenset({"ALLOW", "HOLD", "REDUCE"})
VALID_DUMP = frozenset({"LOW", "MEDIUM", "HIGH"})


def run_trading_llm_shadow(
    inp: LlmContextInput,
    *,
    analysis_summary: dict[str, Any] | None,
    heuristic: LlmContextOutput | None = None,
) -> dict[str, Any]:
    """TRADING_LLM SHADOW 호출. 실패해도 REAL 정책을 바꾸지 않는 payload 반환."""

    base_meta = {
        "model_role": ROLE_TRADING,
        "mode": "SHADOW",
        "affects_real": False,
        "affects_live_arm": False,
        "affects_slot": False,
        "affects_risk": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if not dual_llm_enabled() or not trading_shadow_enabled():
        return {
            **base_meta,
            "ok": False,
            "skipped": True,
            "reason": "TRADING_SHADOW_DISABLED",
            "model": trading_config().model,
        }

    analysis = analysis_summary or {}
    compact = {
        "candidate": inp.candidate,
        "technical": inp.technical,
        "returns": inp.returns,
        "analysis_llm": {
            "market_summary": analysis.get("market_summary"),
            "asset_summary": analysis.get("asset_summary"),
            "news_summary": analysis.get("news_summary"),
            "risk_factors": analysis.get("risk_factors"),
            "tone": analysis.get("tone"),
            "confidence": analysis.get("confidence"),
            "model": analysis.get("model"),
        },
        "heuristic_reference": (
            {
                "recommendation": heuristic.recommendation,
                "entry_quality_score": heuristic.entry_quality_score,
                "risk_flags": heuristic.risk_flags,
            }
            if heuristic is not None
            else None
        ),
        "research_only": True,
        "shadow_only": True,
        "lookahead_forbidden": True,
    }
    cfg = trading_config()
    raw = chat_json_sync(
        config=cfg,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            "Entry Quality / Early Dump Risk를 SHADOW로 평가하세요.\n"
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
            **base_meta,
            "ok": False,
            "timeout": bool(raw.get("timeout")),
            "error": raw.get("error"),
            "latency_ms": raw.get("latency_ms"),
            "model": cfg.model,
            "fallback_to_heuristic": True,
        }

    p = raw["parsed"]
    rec = str(p.get("recommendation") or "").upper()
    if rec not in VALID_REC:
        return {
            **base_meta,
            "ok": False,
            "error": f"INVALID_RECOMMENDATION:{rec}",
            "latency_ms": raw.get("latency_ms"),
            "model": cfg.model,
            "fallback_to_heuristic": True,
        }
    dump = str(p.get("early_dump_risk") or "MEDIUM").upper()
    if dump not in VALID_DUMP:
        dump = "MEDIUM"
    try:
        score = int(p.get("entry_quality_score"))
    except (TypeError, ValueError):
        score = 50
    score = max(0, min(100, score))
    try:
        conf = float(p.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    return {
        **base_meta,
        "ok": True,
        "model": cfg.model,
        "recommendation": rec,
        "entry_quality_score": score,
        "early_dump_risk": dump,
        "confidence": conf,
        "risk_flags": [str(x).upper()[:40] for x in (p.get("risk_flags") or [])[:10]],
        "reason_codes": [str(x)[:40] for x in (p.get("reason_codes") or [])[:10]],
        "short_reason_ko": str(p.get("short_reason_ko") or "")[:240],
        "latency_ms": raw.get("latency_ms"),
        "prompt_tokens": raw.get("prompt_tokens"),
        "output_tokens": raw.get("output_tokens"),
        "fallback_to_heuristic": False,
    }
