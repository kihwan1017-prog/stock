"""STEP N5 — UPBIT News Signal Standardization 상수/정책 (deterministic).

INFORMATIONAL / OBSERVATION ONLY.
POSITIVE ≠ BUY, NEGATIVE ≠ SELL, News Signal ≠ AI Gate Recommendation.
LLM/Ollama 호출 금지. Scanner/Combined Score/Shadow/Trading 연동 금지.
"""

from __future__ import annotations

from datetime import timedelta

SIGNAL_VERSION = "upbit_news_signal_v1"
SIGNAL_POLICY_VERSION = "upbit_news_signal_policy_v1"

# INFORMATIONAL ONLY — trading action 아님
# POSITIVE ≠ BUY / ALLOW
# NEGATIVE ≠ SELL / REDUCE
# NEUTRAL ≠ HOLD

DIRECTIONS = frozenset(
    {"POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED", "UNKNOWN"}
)

STRENGTHS = frozenset({"WEAK", "MODERATE", "STRONG"})

RELIABILITIES = frozenset({"LOW", "MEDIUM", "HIGH"})

SIGNAL_STATUSES = frozenset(
    {"VALID", "LOW_CONFIDENCE", "STALE", "INVALID"}
)

# impact → strength (CRITICAL도 STRONG + reason, 매수 강도 아님)
IMPACT_TO_STRENGTH = {
    "LOW": "WEAK",
    "MEDIUM": "MODERATE",
    "HIGH": "STRONG",
    "CRITICAL": "STRONG",
}

# reliability thresholds (중앙화 — N5 성과 튜닝 금지)
RELIABILITY_HIGH_AI = 0.80
RELIABILITY_HIGH_MAPPING = 0.90
RELIABILITY_MEDIUM_MIN = 0.65

# time_horizon → TTL (News Signal freshness only — Trading Gate 금지)
HORIZON_TTL = {
    "IMMEDIATE": timedelta(hours=6),
    "INTRADAY": timedelta(hours=24),
    "SHORT_TERM": timedelta(hours=72),
    "MEDIUM_TERM": timedelta(days=7),
    "UNKNOWN": timedelta(hours=6),
}

# reason codes (trading action flag 금지)
REASON_CODES = frozenset(
    {
        "DELISTING_EVENT",
        "SECURITY_INCIDENT_EVENT",
        "CRITICAL_IMPACT",
        "LOW_MAPPING_CONFIDENCE",
        "LOW_AI_CONFIDENCE",
        "STALE_NEWS",
        "MULTI_SYMBOL_EVENT",
        "SYMBOL_SPECIFIC_DIRECTION",
        "ARTICLE_LEVEL_DIRECTION",
    }
)
