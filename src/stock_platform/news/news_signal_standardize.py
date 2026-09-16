"""STEP N5 — News Signal deterministic standardization (LLM 금지)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from stock_platform.news.news_ai_analysis_constants import (
    EVENT_TYPES,
    IMPACT_LEVELS,
    SENTIMENTS,
    TIME_HORIZONS,
)
from stock_platform.news.news_signal_constants import (
    DIRECTIONS,
    HORIZON_TTL,
    IMPACT_TO_STRENGTH,
    RELIABILITY_HIGH_AI,
    RELIABILITY_HIGH_MAPPING,
    RELIABILITY_MEDIUM_MIN,
    SIGNAL_POLICY_VERSION,
    SIGNAL_VERSION,
    STRENGTHS,
)


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def mapping_confidence_for_symbol(
    article_raw: dict[str, Any] | None,
    symbol: str,
) -> float:
    """N3.1 evidence에서 해당 symbol mapping_confidence (0~1)."""

    raw = article_raw if isinstance(article_raw, dict) else {}
    sm = raw.get("symbol_mapping") if isinstance(raw, dict) else {}
    if not isinstance(sm, dict):
        return 0.0
    target = str(symbol).upper()
    for ev in sm.get("mappings") or []:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("symbol") or "").upper() != target:
            continue
        if str(ev.get("quality_status") or "") != "TRUSTED":
            continue
        return max(0.0, min(1.0, _as_float(ev.get("mapping_confidence"), 0.0)))
    return 0.0


def compute_strength(news_impact_level: str) -> str:
    level = str(news_impact_level or "").upper()
    return IMPACT_TO_STRENGTH.get(level, "WEAK")


def compute_reliability(
    *,
    news_ai_confidence: float,
    mapping_confidence: float,
) -> str:
    ai = max(0.0, min(1.0, float(news_ai_confidence)))
    mp = max(0.0, min(1.0, float(mapping_confidence)))
    if ai >= RELIABILITY_HIGH_AI and mp >= RELIABILITY_HIGH_MAPPING:
        return "HIGH"
    if min(ai, mp) >= RELIABILITY_MEDIUM_MIN:
        return "MEDIUM"
    return "LOW"


def compute_expires_at(
    *,
    time_horizon: str,
    published_at: datetime | None,
    analyzed_at: datetime | None,
    signal_at: datetime,
) -> datetime:
    ttl = HORIZON_TTL.get(
        str(time_horizon or "UNKNOWN").upper(),
        HORIZON_TTL["UNKNOWN"],
    )
    base = published_at or analyzed_at or signal_at
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + ttl


def build_reason_codes(
    *,
    event_type: str,
    direction: str,
    news_impact_level: str,
    news_ai_confidence: float,
    mapping_confidence: float,
    market_scope: str | None,
    used_symbol_direction: bool,
    is_stale: bool,
) -> list[str]:
    codes: list[str] = []
    et = str(event_type or "").upper()
    if et == "DELISTING" and direction == "NEGATIVE":
        codes.append("DELISTING_EVENT")
    if et == "SECURITY_INCIDENT":
        codes.append("SECURITY_INCIDENT_EVENT")
    if str(news_impact_level or "").upper() == "CRITICAL":
        codes.append("CRITICAL_IMPACT")
    if mapping_confidence < RELIABILITY_MEDIUM_MIN:
        codes.append("LOW_MAPPING_CONFIDENCE")
    if news_ai_confidence < RELIABILITY_MEDIUM_MIN:
        codes.append("LOW_AI_CONFIDENCE")
    if is_stale:
        codes.append("STALE_NEWS")
    if str(market_scope or "").upper() == "MULTI_SYMBOL":
        codes.append("MULTI_SYMBOL_EVENT")
    if used_symbol_direction:
        codes.append("SYMBOL_SPECIFIC_DIRECTION")
    else:
        codes.append("ARTICLE_LEVEL_DIRECTION")
    # 중복 제거, 순서 유지
    out: list[str] = []
    for c in codes:
        if c not in out:
            out.append(c)
    return out


def standardize_symbol_signal(
    *,
    article_id: int,
    news_analysis_id: int,
    symbol: str,
    event_type: str,
    sentiment: str,
    news_impact_level: str,
    time_horizon: str,
    market_scope: str | None,
    news_ai_confidence: float,
    mapping_confidence: float,
    risk_flags: list[str],
    affected_item: dict[str, Any] | None,
    published_at: datetime | None,
    analyzed_at: datetime | None,
    now: datetime | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """1 symbol → 1 News Signal dict (deterministic, Fail Closed)."""

    signal_at = now or datetime.now(timezone.utc)
    if signal_at.tzinfo is None:
        signal_at = signal_at.replace(tzinfo=timezone.utc)

    invalid_reasons: list[str] = []
    sym = str(symbol or "").upper().strip()
    if not sym.startswith("KRW-"):
        invalid_reasons.append("INVALID_SYMBOL")

    et = str(event_type or "").upper()
    if et not in EVENT_TYPES:
        invalid_reasons.append("INVALID_EVENT_TYPE")

    # direction: affected symbol direction 우선
    used_symbol_direction = False
    direction = str(sentiment or "UNKNOWN").upper()
    impact = str(news_impact_level or "").upper()
    if affected_item and isinstance(affected_item, dict):
        d = str(affected_item.get("direction") or "").upper()
        if d in DIRECTIONS:
            direction = d
            used_symbol_direction = True
        ai = str(
            affected_item.get("news_impact_level")
            or affected_item.get("impact_level")
            or ""
        ).upper()
        if ai in IMPACT_LEVELS:
            impact = ai

    if direction not in DIRECTIONS:
        # UNKNOWN으로 강등 (임의 POSITIVE 승격 금지)
        if direction not in SENTIMENTS:
            direction = "UNKNOWN"
        if direction not in DIRECTIONS:
            invalid_reasons.append("INVALID_DIRECTION")

    if impact not in IMPACT_LEVELS:
        invalid_reasons.append("INVALID_IMPACT")

    horizon = str(time_horizon or "UNKNOWN").upper()
    if horizon not in TIME_HORIZONS:
        horizon = "UNKNOWN"

    ai_conf = max(0.0, min(1.0, float(news_ai_confidence)))
    map_conf = max(0.0, min(1.0, float(mapping_confidence)))

    strength = compute_strength(impact if impact in IMPACT_LEVELS else "LOW")
    if strength not in STRENGTHS:
        strength = "WEAK"

    reliability = compute_reliability(
        news_ai_confidence=ai_conf,
        mapping_confidence=map_conf,
    )

    expires_at = compute_expires_at(
        time_horizon=horizon,
        published_at=published_at,
        analyzed_at=analyzed_at,
        signal_at=signal_at,
    )
    is_stale = signal_at >= expires_at

    if invalid_reasons:
        signal_status = "INVALID"
    elif is_stale:
        signal_status = "STALE"
    elif reliability == "LOW":
        signal_status = "LOW_CONFIDENCE"
    else:
        signal_status = "VALID"

    flags = [
        str(f).upper()
        for f in (risk_flags or [])
        if str(f or "").strip()
    ]
    # trading action flag 차단
    banned = {"BUY", "SELL", "ALLOW", "HOLD", "REDUCE", "BUY_BLOCK"}
    flags = [f for f in flags if f not in banned]

    reasons = build_reason_codes(
        event_type=et,
        direction=direction if direction in DIRECTIONS else "UNKNOWN",
        news_impact_level=impact if impact in IMPACT_LEVELS else "LOW",
        news_ai_confidence=ai_conf,
        mapping_confidence=map_conf,
        market_scope=market_scope,
        used_symbol_direction=used_symbol_direction,
        is_stale=is_stale,
    )
    if invalid_reasons:
        reasons = [*invalid_reasons, *reasons]

    return {
        "signal_version": SIGNAL_VERSION,
        "signal_policy_version": SIGNAL_POLICY_VERSION,
        "article_id": int(article_id),
        "news_analysis_id": int(news_analysis_id),
        "symbol": sym,
        "direction": direction if direction in DIRECTIONS else "UNKNOWN",
        "strength": strength,
        "reliability": reliability,
        "signal_status": signal_status,
        "event_type": et if et in EVENT_TYPES else "OTHER",
        "news_impact_level": impact if impact in IMPACT_LEVELS else "LOW",
        "time_horizon": horizon,
        "news_ai_confidence": round(ai_conf, 4),
        "mapping_confidence": round(map_conf, 4),
        "risk_flags": flags,
        "reason_codes": reasons,
        "published_at": published_at,
        "analyzed_at": analyzed_at,
        "signal_at": signal_at,
        "expires_at": expires_at,
        "provenance": provenance or {},
        "informational_only": True,
        "not_a_trade_recommendation": True,
        "positive_neq_buy": True,
        "negative_neq_sell": True,
    }
