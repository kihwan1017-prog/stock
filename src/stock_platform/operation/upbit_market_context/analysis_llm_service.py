"""ANALYSIS_LLM — market/news/asset research summaries (qwen3:1.7b).

lookahead 금지. REAL 주문 무관. fail-open.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    ROLE_ANALYSIS,
    analysis_cache,
    analysis_config,
    chat_json_sync,
    dual_llm_enabled,
    record_cache_hit,
    record_stat,
)
from stock_platform.operation.upbit_market_context.schemas import LlmContextInput

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "market_summary": {"type": "string"},
        "asset_summary": {"type": "string"},
        "news_summary": {"type": "string"},
        "risk_factors": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "tone": {
            "type": "string",
            "enum": ["BULLISH", "NEUTRAL", "BEARISH", "CAUTION"],
        },
    },
    "required": [
        "market_summary",
        "asset_summary",
        "news_summary",
        "risk_factors",
        "confidence",
    ],
}

SYSTEM_PROMPT = (
    "당신은 UPBIT 연구용 ANALYSIS_LLM입니다. "
    "시장·종목·뉴스 Context만 요약합니다. REAL 주문/진입 지시를 하지 마세요. "
    "미래 가격을 추측하지 마세요. 숫자와 공지 핵심을 왜곡하지 마세요. "
    "한국어로 간결히. JSON만 반환."
)


def _cache_key(inp: LlmContextInput, *, symbol: str) -> str:
    """context_as_of + market/news fingerprint — 분 단위 버킷."""

    as_of = str(inp.context_as_of or "")[:16]  # YYYY-MM-DDTHH:MM
    blob = json.dumps(
        {
            "as_of": as_of,
            "symbol": symbol,
            "market": inp.market_context,
            "asset": inp.asset_context,
            "news_titles": [
                (n.get("title") if isinstance(n, dict) else None)
                for n in (inp.news or [])[:5]
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _fallback_analysis(inp: LlmContextInput, *, reason: str) -> dict[str, Any]:
    fear = ((inp.market_context or {}).get("fear_greed") or {}).get("value_json") or {}
    adv = ((inp.market_context or {}).get("advancing_asset_ratio") or {}).get(
        "value_json"
    ) or {}
    news_titles = [
        str(n.get("title") or "")[:80]
        for n in (inp.news or [])
        if isinstance(n, dict)
    ][:3]
    return {
        "model_role": ROLE_ANALYSIS,
        "model": analysis_config().model,
        "ok": False,
        "fallback": True,
        "fallback_reason": reason,
        "market_summary": (
            f"F&G={fear.get('value')} {fear.get('classification')}; "
            f"상승비중={adv.get('ratio')}"
        ),
        "asset_summary": str((inp.asset_context or {}) or "종목 context 없음")[:240],
        "news_summary": "; ".join(news_titles) or "관련 뉴스 없음",
        "risk_factors": ["CONTEXT_FALLBACK", reason[:80]],
        "confidence": 0.0,
        "tone": "NEUTRAL",
        "latency_ms": 0,
        "context_as_of": inp.context_as_of,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def run_analysis_llm(
    inp: LlmContextInput,
    *,
    symbol: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """ANALYSIS_LLM 호출 또는 캐시. 실패 시 fallback 요약."""

    if not dual_llm_enabled():
        return _fallback_analysis(inp, reason="DUAL_LLM_DISABLED")

    key = _cache_key(inp, symbol=symbol)
    if not force_refresh:
        cached = analysis_cache.get(key)
        if cached is not None:
            record_cache_hit()
            out = dict(cached)
            out["cache_hit"] = True
            return out

    # Trading이 원문 전체를 다시 넣지 않도록 요약용 compact payload
    compact = {
        "context_as_of": inp.context_as_of,
        "symbol": symbol,
        "candidate": {
            k: (inp.candidate or {}).get(k)
            for k in ("symbol", "rank", "score", "recommendation")
        },
        "market_context": inp.market_context,
        "asset_context": inp.asset_context,
        "news": [
            {
                "type": n.get("type") or n.get("source"),
                "title": n.get("title"),
                "summary": (n.get("summary") or n.get("description") or "")[:200],
                "published_at": n.get("published_at"),
            }
            for n in (inp.news or [])[:5]
            if isinstance(n, dict)
        ],
        "asset_description": {
            k: (inp.asset_description or {}).get(k)
            for k in ("project_summary", "sector", "known_risks")
        },
        "research_only": True,
        "lookahead_forbidden": True,
    }
    cfg = analysis_config()
    raw = chat_json_sync(
        config=cfg,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            "다음 UPBIT 연구 Context를 요약하세요. "
            "detected/context_as_of 이후 정보는 없습니다.\n"
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
        return _fallback_analysis(
            inp,
            reason=str(raw.get("error") or "ANALYSIS_LLM_FAILED")[:120],
        )

    parsed = raw["parsed"]
    result = {
        "model_role": ROLE_ANALYSIS,
        "model": cfg.model,
        "ok": True,
        "fallback": False,
        "cache_hit": False,
        "market_summary": str(parsed.get("market_summary") or "")[:800],
        "asset_summary": str(parsed.get("asset_summary") or "")[:800],
        "news_summary": str(parsed.get("news_summary") or "")[:800],
        "risk_factors": [
            str(x)[:80] for x in (parsed.get("risk_factors") or [])[:8]
        ],
        "confidence": float(parsed.get("confidence") or 0.0),
        "tone": str(parsed.get("tone") or "NEUTRAL"),
        "latency_ms": raw.get("latency_ms"),
        "context_as_of": inp.context_as_of,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "prompt_tokens": raw.get("prompt_tokens"),
        "output_tokens": raw.get("output_tokens"),
    }
    ttl = float(get_settings().analysis_llm_cache_ttl_seconds)
    analysis_cache.put(key, result, ttl_seconds=ttl)
    return result
