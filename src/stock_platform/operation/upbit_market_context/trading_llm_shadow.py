"""TRADING_LLM SHADOW — Entry Quality / Early Dump (qwen3.5:2b) + CLEAN RAG.

결과는 SHADOW ONLY. REAL candidate/slot/order/risk/LIVE/ARM에 영향 금지.
timeout/error 시 호출측이 heuristic을 유지한다.
"""

from __future__ import annotations

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
from stock_platform.operation.upbit_market_context.prompt_versions import (
    TRADING_PROMPT_VERSION,
    settings_fingerprint,
)
from stock_platform.operation.upbit_market_context.schemas import (
    LlmContextInput,
    LlmContextOutput,
)
from stock_platform.operation.upbit_market_context.trading_decision_contract import (
    TRADING_SYSTEM_PROMPT_V2,
    build_trading_decision_payload,
    build_trading_user_prompt,
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
        "confidence",
        "risk_flags",
        "reason_codes",
    ],
}

# v2: SHADOW != ALWAYS HOLD. recommendation은 주문 명령이 아님.
SYSTEM_PROMPT = TRADING_SYSTEM_PROMPT_V2

VALID_REC = frozenset({"ALLOW", "HOLD", "REDUCE"})
VALID_RISK = frozenset({"LOW", "MEDIUM", "HIGH"})


def run_trading_llm_shadow(
    inp: LlmContextInput,
    *,
    analysis_summary: dict[str, Any] | None,
    heuristic: LlmContextOutput | None = None,
    rag_examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """TRADING_LLM SHADOW 호출. 실패해도 REAL 정책을 바꾸지 않는 payload 반환."""

    cfg = trading_config()
    base_meta = {
        "model_role": ROLE_TRADING,
        "mode": "SHADOW",
        "prompt_version": TRADING_PROMPT_VERSION,
        "model_name": cfg.model,
        "settings_fingerprint": settings_fingerprint(
            model=cfg.model,
            role=ROLE_TRADING,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            prompt_version=TRADING_PROMPT_VERSION,
        ),
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
            "model": cfg.model,
        }

    # 고정 입력 구조 — 현재 후보 미래 outcome 금지. SHADOW != ALWAYS HOLD.
    compact = build_trading_decision_payload(
        inp,
        analysis_summary=analysis_summary,
        heuristic=heuristic,
        rag_examples=rag_examples,
    )
    raw = chat_json_sync(
        config=cfg,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=build_trading_user_prompt(compact),
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
            "rag_example_count": len(rag_examples or []),
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
            "rag_example_count": len(rag_examples or []),
        }
    dump = str(p.get("early_dump_risk") or "MEDIUM").upper()
    if dump not in VALID_RISK:
        dump = "MEDIUM"
    fee = str(p.get("fee_churn_risk") or "MEDIUM").upper()
    if fee not in VALID_RISK:
        fee = "MEDIUM"
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
    reason_ko = str(p.get("reason_ko") or p.get("short_reason_ko") or "")[:240]

    return {
        **base_meta,
        "ok": True,
        "model": cfg.model,
        "recommendation": rec,
        "entry_quality_score": score,
        "early_dump_risk": dump,
        "fee_churn_risk": fee,
        "confidence": conf,
        "risk_flags": [str(x).upper()[:40] for x in (p.get("risk_flags") or [])[:10]],
        "reason_codes": [str(x)[:40] for x in (p.get("reason_codes") or [])[:10]],
        "reason_ko": reason_ko,
        "short_reason_ko": reason_ko,  # 하위호환
        "latency_ms": raw.get("latency_ms"),
        "prompt_tokens": raw.get("prompt_tokens"),
        "output_tokens": raw.get("output_tokens"),
        "fallback_to_heuristic": False,
        "rag_example_count": len(rag_examples or []),
    }
