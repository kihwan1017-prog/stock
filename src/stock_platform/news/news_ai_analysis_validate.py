"""STEP N4 — AI 응답 검증 (Fail Closed)."""

from __future__ import annotations

from typing import Any

from stock_platform.news.news_ai_analysis_constants import (
    EVENT_TYPES,
    IMPACT_LEVELS,
    MARKET_SCOPES,
    RISK_FLAGS,
    SENTIMENTS,
    TIME_HORIZONS,
)


class NewsAIValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _canon_symbol(raw: str, trusted: set[str]) -> str | None:
    """TRUSTED 집합 안의 심볼로만 정규화. 없으면 None."""

    sym = str(raw or "").upper().strip()
    if not sym:
        return None
    if sym in trusted:
        return sym
    prefixed = f"KRW-{sym}"
    if prefixed in trusted:
        return prefixed
    return None


def validate_and_normalize_result(
    raw: dict[str, Any],
    *,
    trusted_symbols: list[str],
) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        raise NewsAIValidationError("EMPTY_OR_INVALID", "empty/non-object response")

    trusted = {s.upper() for s in trusted_symbols}

    event_type = str(raw.get("event_type") or "").upper()
    if event_type not in EVENT_TYPES:
        raise NewsAIValidationError("UNKNOWN_EVENT_TYPE", f"event_type={event_type}")

    sentiment = str(raw.get("sentiment") or "").upper()
    if sentiment not in SENTIMENTS:
        raise NewsAIValidationError("UNKNOWN_SENTIMENT", f"sentiment={sentiment}")

    impact = str(
        raw.get("news_impact_level") or raw.get("impact_level") or ""
    ).upper()
    if impact not in IMPACT_LEVELS:
        raise NewsAIValidationError("UNKNOWN_IMPACT", f"impact={impact}")

    horizon_raw = str(raw.get("time_horizon") or "").upper()
    horizon = horizon_raw
    if horizon not in TIME_HORIZONS:
        # "IMMEDIATE|SHORT_TERM" 같은 오출력 → 첫 유효 enum만 채택
        picked = None
        for part in horizon_raw.replace("/", "|").split("|"):
            part = part.strip()
            if part in TIME_HORIZONS:
                picked = part
                break
        if picked is None:
            raise NewsAIValidationError("UNKNOWN_HORIZON", f"horizon={horizon_raw}")
        horizon = picked

    scope = str(raw.get("market_scope") or "").upper()
    if scope not in MARKET_SCOPES:
        raise NewsAIValidationError("UNKNOWN_SCOPE", f"scope={scope}")

    try:
        confidence = float(raw.get("news_ai_confidence", raw.get("confidence")))
    except (TypeError, ValueError) as exc:
        raise NewsAIValidationError(
            "INVALID_CONFIDENCE", "confidence not numeric"
        ) from exc
    # 0~100 퍼센트 오출력 → 0~1 스케일
    if 1.0 < confidence <= 100.0:
        confidence = confidence / 100.0
    if not 0.0 <= confidence <= 1.0:
        raise NewsAIValidationError(
            "INVALID_CONFIDENCE", f"confidence={confidence}"
        )

    summary = str(raw.get("summary") or "").strip()
    reasoning = str(raw.get("reasoning_summary") or "").strip()
    if not summary:
        raise NewsAIValidationError("EMPTY_SUMMARY", "summary required")

    affected_in = raw.get("affected_symbols") or []
    if not isinstance(affected_in, list):
        raise NewsAIValidationError(
            "INVALID_AFFECTED", "affected_symbols must be list"
        )

    affected: list[dict[str, Any]] = []
    hallucinated: list[str] = []
    for item in affected_in:
        if not isinstance(item, dict):
            continue
        raw_sym = str(item.get("symbol") or "").upper().strip()
        if not raw_sym:
            continue
        sym = _canon_symbol(raw_sym, trusted)
        if sym is None:
            hallucinated.append(raw_sym)
            continue
        direction = str(item.get("direction") or "UNKNOWN").upper()
        if direction not in SENTIMENTS:
            direction = "UNKNOWN"
        try:
            item_impact = str(
                item.get("news_impact_level") or item.get("impact_level") or "LOW"
            ).upper()
            if item_impact not in IMPACT_LEVELS:
                item_impact = "LOW"
            item_conf = float(item.get("confidence", 0.0))
            if 1.0 < item_conf <= 100.0:
                item_conf = item_conf / 100.0
        except (TypeError, ValueError):
            item_impact = "LOW"
            item_conf = 0.0
        item_conf = max(0.0, min(1.0, item_conf))
        affected.append(
            {
                "symbol": sym,
                "direction": direction,
                "news_impact_level": item_impact,
                "confidence": round(item_conf, 4),
            }
        )

    # TRUSTED가 있는데 AI가 전부 환각이면 Fail Closed
    if hallucinated and not affected and trusted:
        raise NewsAIValidationError(
            "HALLUCINATED_SYMBOLS",
            f"hallucinated={hallucinated[:5]}",
        )

    flags_in = raw.get("risk_flags") or []
    if not isinstance(flags_in, list):
        raise NewsAIValidationError("INVALID_RISK_FLAGS", "risk_flags must be list")
    flags: list[str] = []
    for f in flags_in:
        key = str(f or "").upper().strip()
        if key in RISK_FLAGS:
            flags.append(key)
        # unknown flags dropped (not fail) — enum validation soft

    return {
        "event_type": event_type,
        "sentiment": sentiment,
        "news_impact_level": impact,
        "time_horizon": horizon,
        "market_scope": scope,
        "summary": summary[:4000],
        "reasoning_summary": reasoning[:4000],
        "news_ai_confidence": round(confidence, 4),
        "affected_symbols": affected,
        "risk_flags": flags,
        "dropped_hallucinated_symbols": hallucinated,
    }
