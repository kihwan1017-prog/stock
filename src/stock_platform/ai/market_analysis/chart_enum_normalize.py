"""CHART LLM 응답 필드 별칭 → 프로젝트 enum 정규화."""

from __future__ import annotations

from typing import Any

_TREND_ALIASES = {
    "BULLISH": "UPTREND",
    "BEARISH": "DOWNTREND",
    "NEUTRAL": "SIDEWAYS",
    "UP": "UP",
    "DOWN": "DOWN",
    "SIDEWAYS": "SIDEWAYS",
    "UPTREND": "UPTREND",
    "DOWNTREND": "DOWNTREND",
    "STRONG_UPTREND": "STRONG_UPTREND",
    "STRONG_DOWNTREND": "STRONG_DOWNTREND",
    "UNCERTAIN": "UNCERTAIN",
    "UNKNOWN": "UNKNOWN",
}

_MOMENTUM_ALIASES = {
    "BULLISH": "BULLISH",
    "BEARISH": "BEARISH",
    "NEUTRAL": "NEUTRAL",
    "UNKNOWN": "UNKNOWN",
    "POSITIVE": "BULLISH",
    "NEGATIVE": "BEARISH",
    "STRONG": "BULLISH",
    "WEAK": "NEUTRAL",
    "UP": "BULLISH",
    "DOWN": "BEARISH",
}

_VOL_ALIASES = {
    "VERY_LOW": "VERY_LOW",
    "LOW": "LOW",
    "NORMAL": "NORMAL",
    "MEDIUM": "NORMAL",
    "HIGH": "HIGH",
    "VERY_HIGH": "VERY_HIGH",
    "UNKNOWN": "UNKNOWN",
}


def normalize_chart_result_enums(payload: dict[str, Any]) -> dict[str, Any]:
    """검증 전 enum 별칭만 정규화 — 값을 날조하지 않음."""

    out = dict(payload)
    result = out.get("result")
    if not isinstance(result, dict):
        return out
    body = dict(result)
    trend = str(body.get("trend") or "").strip().upper()
    mom = str(body.get("momentum") or "").strip().upper()
    vol = str(body.get("volatility") or "").strip().upper()
    if trend in _TREND_ALIASES:
        body["trend"] = _TREND_ALIASES[trend]
    if mom in _MOMENTUM_ALIASES:
        body["momentum"] = _MOMENTUM_ALIASES[mom]
    if vol in _VOL_ALIASES:
        body["volatility"] = _VOL_ALIASES[vol]
    out["result"] = body
    return out
