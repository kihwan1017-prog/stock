"""Chart/Market safe_result → AI Gate recommendation enrichment.

LLM 차트 스키마에는 BUY/SELL이 없다.
Gate용 ALLOW/HOLD/REDUCE는 검증된 chart 필드에서 결정적으로 매핑한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


ALLOWED_RECOMMENDATIONS = frozenset({"ALLOW", "HOLD", "REDUCE"})


def map_chart_to_gate_decision(
    *,
    trend: str | None,
    momentum: str | None,
    volatility: str | None,
    confidence: float | Decimal | None,
    min_confidence: float = 0.4,
) -> dict[str, Any]:
    """검증된 chart 필드로 Gate recommendation 생성."""

    trend_u = str(trend or "UNKNOWN").strip().upper()
    momentum_u = str(momentum or "UNKNOWN").strip().upper()
    vol_u = str(volatility or "UNKNOWN").strip().upper()
    try:
        conf = float(confidence) if confidence is not None else 0.0
    except (TypeError, ValueError):
        conf = 0.0
    if conf < 0.0 or conf > 1.0:
        return {
            "recommendation": "HOLD",
            "risk_level": "HIGH",
            "validated_mapping": False,
            "reason_code": "CONFIDENCE_OUT_OF_RANGE",
            "reasons": ["confidence must be in [0,1]"],
        }

    reasons: list[str] = [
        f"trend={trend_u}",
        f"momentum={momentum_u}",
        f"volatility={vol_u}",
        f"confidence={conf:.3f}",
    ]

    bullish = trend_u in {"STRONG_UPTREND", "UPTREND", "UP"} and momentum_u == "BULLISH"
    bearish = (
        trend_u in {"STRONG_DOWNTREND", "DOWNTREND", "DOWN"}
        or momentum_u == "BEARISH"
    )
    high_vol = vol_u in {"HIGH", "VERY_HIGH"}

    if conf < float(min_confidence):
        return {
            "recommendation": "HOLD",
            "risk_level": "MEDIUM" if not high_vol else "HIGH",
            "validated_mapping": True,
            "reason_code": "LOW_CONFIDENCE",
            "reasons": reasons + ["confidence below min"],
        }
    if bearish:
        return {
            "recommendation": "HOLD",
            "risk_level": "HIGH" if high_vol else "MEDIUM",
            "validated_mapping": True,
            "reason_code": "BEARISH_CONTEXT",
            "reasons": reasons,
        }
    if bullish and high_vol:
        return {
            "recommendation": "REDUCE",
            "risk_level": "HIGH",
            "validated_mapping": True,
            "reason_code": "BULLISH_HIGH_VOL",
            "reasons": reasons,
        }
    if bullish:
        return {
            "recommendation": "ALLOW",
            "risk_level": "LOW" if vol_u in {"VERY_LOW", "LOW"} else "MEDIUM",
            "validated_mapping": True,
            "reason_code": "BULLISH_TREND",
            "reasons": reasons,
        }
    return {
        "recommendation": "HOLD",
        "risk_level": "HIGH" if high_vol else "MEDIUM",
        "validated_mapping": True,
        "reason_code": "NEUTRAL_OR_UNCERTAIN",
        "reasons": reasons,
    }


def enrich_safe_result_for_gate(
    safe_result: dict[str, Any] | None,
    *,
    news_sentiment: str = "NO_DATA",
    min_confidence: float = 0.4,
) -> dict[str, Any]:
    """safe_result에 Gate 필드를 추가한다 (원본 chart result 유지)."""

    payload = dict(safe_result or {})
    result_body = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    conf = payload.get("confidence")
    if conf is None and isinstance(result_body, dict):
        conf = result_body.get("confidence")

    mapped = map_chart_to_gate_decision(
        trend=result_body.get("trend") if result_body else payload.get("trend"),
        momentum=(
            result_body.get("momentum") if result_body else payload.get("momentum")
        ),
        volatility=(
            result_body.get("volatility")
            if result_body
            else payload.get("volatility")
        ),
        confidence=conf,
        min_confidence=min_confidence,
    )
    rec = str(mapped["recommendation"]).upper()
    if rec not in ALLOWED_RECOMMENDATIONS:
        mapped["recommendation"] = "HOLD"
        mapped["validated_mapping"] = False
        mapped["reason_code"] = "INVALID_RECOMMENDATION"

    summary = (
        payload.get("reasoning_summary")
        or (result_body.get("summary") if result_body else None)
        or ""
    )
    payload["recommendation"] = mapped["recommendation"]
    payload["risk_level"] = mapped["risk_level"]
    payload["news_sentiment"] = str(news_sentiment or "NO_DATA").upper()
    payload["reasons"] = mapped["reasons"]
    payload["summary"] = str(summary)[:500]
    payload["gate_enrichment"] = {
        "reason_code": mapped["reason_code"],
        "validated_mapping": bool(mapped["validated_mapping"]),
        "source": "chart_field_mapping_v1",
    }
    return payload


def validate_gate_recommendation_fields(payload: dict[str, Any]) -> list[str]:
    """Gate enrichment 필드 검증 — malformed면 에러 코드 목록."""

    errors: list[str] = []
    rec = str(payload.get("recommendation") or "").upper()
    if rec not in ALLOWED_RECOMMENDATIONS:
        errors.append("INVALID_RECOMMENDATION")
    conf = payload.get("confidence")
    if conf is not None:
        try:
            c = float(conf)
            if c < 0.0 or c > 1.0:
                errors.append("CONFIDENCE_OUT_OF_RANGE")
        except (TypeError, ValueError):
            errors.append("CONFIDENCE_NOT_NUMERIC")
    return errors
