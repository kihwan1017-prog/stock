"""TRADING_LLM SHADOW — Entry Quality / Early Dump (qwen3.5:2b) + CLEAN RAG.

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
from stock_platform.operation.upbit_market_context.prompt_versions import (
    TRADING_PROMPT_VERSION,
    settings_fingerprint,
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

SYSTEM_PROMPT = (
    "당신은 UPBIT TRADING_LLM SHADOW입니다. "
    "ALLOW|HOLD|REDUCE 보조판단만 합니다. REAL 주문을 만들지 마세요. "
    "미래 수익률은 모릅니다. Analysis 요약·기술지표·과거 유사 CLEAN 사례만 사용하세요. "
    "RAG 사례의 과거 결과는 참고 예제일 뿐, 현재 후보의 미래가 아닙니다. JSON만."
)

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

    analysis = analysis_summary or {}
    # 고정 입력 구조 — 현재 후보 미래 outcome 금지
    compact = {
        "candidate": inp.candidate,
        "technical": {
            "rsi": (inp.technical or {}).get("rsi14"),
            "ma_separation_pct": (inp.technical or {}).get("ma_separation_pct"),
            "volume_ratio": (inp.technical or {}).get("volume_surge"),
            "pre_entry_return": (inp.returns or {}).get("pre_entry_return_5m")
            if isinstance(inp.returns, dict)
            else None,
            "raw_technical": inp.technical,
        },
        "analysis": {
            "market_state": analysis.get("market_summary") or analysis.get("tone"),
            "asset_state": analysis.get("asset_summary"),
            "news_state": analysis.get("news_summary"),
            "risk_flags": analysis.get("risk_factors"),
            "confidence": analysis.get("confidence"),
            "model": analysis.get("model"),
        },
        "rag_examples": [
            {
                "case_id": e.get("case_id"),
                "similarity_score": e.get("similarity_score"),
                "entry_summary": e.get("entry_summary"),
                "actual_label": e.get("actual_label"),
                "mfe": e.get("mfe"),
                "mae": e.get("mae"),
            }
            for e in (rag_examples or [])[:5]
        ],
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
        "current_future_outcome_forbidden": True,
    }
    raw = chat_json_sync(
        config=cfg,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            "Entry Quality / Early Dump / Fee Churn Risk를 SHADOW로 평가하세요.\n"
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
