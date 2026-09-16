"""KIWOOM ANALYSIS_LLM — stock/news/disclosure research summaries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from stock_platform.operation.dual_llm.markets import MARKET_KIWOOM
from stock_platform.operation.dual_llm.prompt_versions import (
    ANALYSIS_KIWOOM_PROMPT_V1,
    settings_fingerprint,
)
from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    ROLE_ANALYSIS,
    analysis_config,
    chat_json_sync,
    dual_llm_enabled,
    record_stat,
)

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "market_state": {
            "type": "string",
            "enum": ["STRONG", "NORMAL", "WEAK", "UNKNOWN"],
        },
        "asset_state": {
            "type": "string",
            "enum": ["STRONG", "NORMAL", "WEAK", "UNKNOWN"],
        },
        "news_state": {
            "type": "string",
            "enum": ["POSITIVE", "NEUTRAL", "NEGATIVE", "UNKNOWN"],
        },
        "disclosure_state": {
            "type": "string",
            "enum": [
                "POSITIVE",
                "NEUTRAL",
                "NEGATIVE",
                "MIXED",
                "NONE",
                "UNKNOWN",
            ],
        },
        "risk_level": {
            "type": "string",
            "enum": ["LOW", "MEDIUM", "HIGH"],
        },
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "summary_ko": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": [
        "market_state",
        "asset_state",
        "news_state",
        "disclosure_state",
        "risk_level",
        "risk_flags",
        "summary_ko",
        "confidence",
    ],
}

SYSTEM_PROMPT = (
    "당신은 KIWOOM(KRX) 연구용 ANALYSIS_LLM입니다. "
    "시장·종목·뉴스·공시 Context만 요약합니다. REAL 주문/진입 지시를 하지 마세요. "
    "없는 사실을 만들어내지 마세요. UNKNOWN을 허용합니다. JSON만."
)


def _fallback(ctx: dict[str, Any], *, reason: str) -> dict[str, Any]:
    news = ctx.get("news") or []
    disc = ctx.get("disclosures") or []
    return {
        "market": MARKET_KIWOOM,
        "model_role": ROLE_ANALYSIS,
        "model": analysis_config().model,
        "prompt_version": ANALYSIS_KIWOOM_PROMPT_V1,
        "ok": False,
        "fallback": True,
        "fallback_reason": reason,
        "market_state": "UNKNOWN",
        "asset_state": "UNKNOWN",
        "news_state": "UNKNOWN" if not news else "NEUTRAL",
        "disclosure_state": "NONE" if not disc else "UNKNOWN",
        "risk_level": "MEDIUM",
        "risk_flags": ["CONTEXT_FALLBACK"],
        "summary_ko": "분석 실패 — fail-open (연구 전용)",
        "confidence": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def run_kiwoom_analysis_llm(ctx: dict[str, Any]) -> dict[str, Any]:
    if not dual_llm_enabled():
        return _fallback(ctx, reason="DUAL_LLM_DISABLED")

    cfg = analysis_config()
    compact = {
        "market": MARKET_KIWOOM,
        "symbol": ctx.get("symbol"),
        "technical": ctx.get("technical"),
        "asset_context": ctx.get("asset_context"),
        "market_context": ctx.get("market_context"),
        "news": (ctx.get("news") or [])[:5],
        "disclosures": (ctx.get("disclosures") or [])[:5],
        "research_only": True,
        "lookahead_forbidden": True,
    }
    raw = chat_json_sync(
        config=cfg,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            "다음 KIWOOM ENTRY 연구 Context를 요약하세요. "
            "평가 시각 이후 정보는 없습니다.\n"
            + json.dumps(compact, ensure_ascii=False, default=str)
        ),
        response_schema=ANALYSIS_SCHEMA,
    )
    record_stat(
        ROLE_ANALYSIS,
        ok=bool(raw.get("ok")),
        timeout=bool(raw.get("timeout")),
        latency_ms=raw.get("latency_ms"),
    )
    if not raw.get("ok") or not isinstance(raw.get("parsed"), dict):
        return _fallback(ctx, reason=str(raw.get("error") or "ANALYSIS_FAILED")[:120])

    p = raw["parsed"]
    return {
        "market": MARKET_KIWOOM,
        "model_role": ROLE_ANALYSIS,
        "model": cfg.model,
        "model_name": cfg.model,
        "prompt_version": ANALYSIS_KIWOOM_PROMPT_V1,
        "settings_fingerprint": settings_fingerprint(
            model=cfg.model,
            role=ROLE_ANALYSIS,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            prompt_version=ANALYSIS_KIWOOM_PROMPT_V1,
            market=MARKET_KIWOOM,
        ),
        "ok": True,
        "fallback": False,
        "market_state": str(p.get("market_state") or "UNKNOWN").upper(),
        "asset_state": str(p.get("asset_state") or "UNKNOWN").upper(),
        "news_state": str(p.get("news_state") or "UNKNOWN").upper(),
        "disclosure_state": str(p.get("disclosure_state") or "UNKNOWN").upper(),
        "risk_level": str(p.get("risk_level") or "MEDIUM").upper(),
        "risk_flags": [str(x).upper()[:40] for x in (p.get("risk_flags") or [])[:10]],
        "risk_factors": [str(x).upper()[:40] for x in (p.get("risk_flags") or [])[:10]],
        "summary_ko": str(p.get("summary_ko") or "")[:800],
        "market_summary": str(p.get("summary_ko") or "")[:400],
        "asset_summary": str(p.get("asset_state") or ""),
        "news_summary": str(p.get("news_state") or ""),
        "tone": (
            "CAUTION"
            if str(p.get("risk_level") or "").upper() == "HIGH"
            else "NEUTRAL"
        ),
        "confidence": max(0.0, min(1.0, float(p.get("confidence") or 0.0))),
        "latency_ms": raw.get("latency_ms"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
