"""STEP N6 — News Combined Shadow Experiment 정책 (CONTROL 비수정).

EXPERIMENT ONLY. scanner_score ≠ experimental_combined_score.
experimental_decision ≠ AI Gate. LLM 금지. LOOK-AHEAD 금지.
"""

from __future__ import annotations

from datetime import timedelta

EXPERIMENT_VERSION = "upbit_news_combined_shadow_v1"
COMBINED_POLICY_VERSION = "upbit_news_combined_policy_v1"

# News lookback (VALID이어도 T0-24h 이전 published는 contribution 0)
NEWS_LOOKBACK = timedelta(hours=24)

NEWS_SCORE_MAX_ADJUSTMENT = 10.0

DIRECTION_VALUE = {
    "POSITIVE": 1.0,
    "NEGATIVE": -1.0,
    "NEUTRAL": 0.0,
    "MIXED": 0.0,
    "UNKNOWN": 0.0,
}

STRENGTH_WEIGHT = {
    "WEAK": 0.5,
    "MODERATE": 1.0,
    "STRONG": 1.5,
}

RELIABILITY_WEIGHT = {
    "LOW": 0.25,
    "MEDIUM": 0.60,
    "HIGH": 1.00,
}

# age → recency weight (deterministic decay)
# (max_age_seconds inclusive, weight)
RECENCY_BUCKETS = (
    (3600, 1.00),
    (6 * 3600, 0.75),
    (12 * 3600, 0.50),
    (24 * 3600, 0.25),
)

NEWS_COMPONENT_CLAMP = 3.0

DECISION_BOOST = "BOOST"
DECISION_UNCHANGED = "UNCHANGED"
DECISION_DEPRIORITIZE = "DEPRIORITIZE"
DECISION_THRESHOLD = 0.25

NEWS_STATUS_NO_NEWS = "NO_NEWS"
NEWS_STATUS_MATCHED = "NEWS_MATCHED"
NEWS_STATUS_EXCLUDED_ONLY = "EXCLUDED_ONLY"  # signals 있으나 contribution 0

EVAL_PENDING = "PENDING"
EVAL_ACTIVE = "ACTIVE"
EVAL_COMPLETED = "COMPLETED"
EVAL_INCOMPLETE = "INCOMPLETE"
EVAL_FAILED = "FAILED"
