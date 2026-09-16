"""STEP 11-9 — AI Candidate Assessment constants."""

from __future__ import annotations

ASSESSMENT_ENGINE_VERSION = "11.9.0"
REFERENCE_DISCLAIMER = (
    "AI 후보 평가는 참고용 초안이며 실제 매매 후보, 매수·매도 신호 또는 주문 지시가 아닙니다."
)
REVIEW_QUALITY_LABEL = "AI 후보 평가 품질 승인"

ASSESSMENT_TYPES = frozenset({"STOCK", "CRYPTO"})
ASSESSMENT_STATUS = frozenset(
    {
        "DRAFT",
        "QUEUED",
        "RUNNING",
        "VALIDATED",
        "VALIDATED_WITH_WARNINGS",
        "BLOCKED",
        "INVALID",
        "FAILED",
        "CANCELLED",
        "REVIEW_PENDING",
        "REVIEW_APPROVED",
        "REVIEW_REJECTED",
        "SUPERSEDED",
        "ARCHIVED",
    }
)
EVIDENCE_TYPES = frozenset(
    {"NEWS", "DISCLOSURE", "CHART", "MARKET", "REVIEW", "FUNDAMENTAL", "OTHER"}
)
TEMPORAL_STATUS = frozenset(
    {"ALIGNED", "ACCEPTABLE", "STALE", "CONFLICTED", "UNKNOWN"}
)
CONFLICT_STATUS = frozenset(
    {"NO_CONFLICT", "MINOR_CONFLICT", "MAJOR_CONFLICT", "INSUFFICIENT_EVIDENCE"}
)
DIRECTIONS = frozenset({"POSITIVE", "NEGATIVE", "NEUTRAL", "UNCERTAIN"})

MAX_BATCH_MOCK = 100
MAX_BATCH_EXTERNAL = 10
MAX_NEWS_EVIDENCE = 5
MAX_DISCLOSURE_EVIDENCE = 3
MAX_EVIDENCE_AGE_DAYS_KRX = 14
MAX_EVIDENCE_AGE_DAYS_UPBIT = 7
MAX_CONFIDENCE_NO_REVIEW = 0.75
MAX_CONFIDENCE_METADATA_ONLY = 0.70
MAX_CONFIDENCE_MAJOR_CONFLICT = 0.60
MAX_CONFIDENCE_STALE = 0.65
SCORE_MIN = 0
SCORE_MAX = 100

FORBIDDEN_RESULT_KEYS = frozenset(
    {
        "buy",
        "sell",
        "hold_signal",
        "execute",
        "order",
        "submit_order",
        "target_price",
        "entry_price",
        "stop_loss",
        "take_profit",
        "position_size",
        "allocation",
        "guaranteed_return",
        "candidate_approved",
        "strategy_id",
        "live",
        "arm",
        "runtime_resume",
        "scheduler_start",
        "api_key",
        "candidate_score",
        "ranking_score",
        "buy_score",
        "order_score",
    }
)

# document/market analysis에서 유효한 근거 상태
VALID_SOURCE_STATUSES = frozenset(
    {"VALIDATED_ANALYSIS", "VALIDATED_WITH_WARNINGS"}
)

# Review에서 제외할 결정
EXCLUDED_REVIEW_DECISIONS = frozenset({"REJECTED", "REVISION_REQUESTED"})

# Review 승인으로 인정
APPROVED_REVIEW_DECISIONS = frozenset({"APPROVED", "APPROVED_WITH_WARNINGS"})

HARD_BATCH_CAP = 100
