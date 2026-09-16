"""STEP 11-10 — Multi-AI Consensus constants."""

from __future__ import annotations

CONSENSUS_ENGINE_VERSION = "11.10.0"
DETERMINISTIC_VERSION = "det-1.0.0"
WEIGHT_VERSION = "weight-1.0.0"
REFERENCE_DISCLAIMER = (
    "Multi-AI Consensus는 여러 AI 후보 평가를 비교한 참고용 품질 합의 초안이며, "
    "실제 후보 등록·매수·매도·주문 지시가 아닙니다."
)
REVIEW_QUALITY_LABEL = "AI Consensus 품질 승인"

CONSENSUS_TYPES = frozenset({"STOCK", "CRYPTO"})
CALCULATION_MODES = frozenset({"DETERMINISTIC_ONLY", "DETERMINISTIC_PLUS_SYNTHESIS"})
CONSENSUS_STATUS = frozenset(
    {
        "DRAFT",
        "INPUT_VALIDATED",
        "CALCULATED",
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
AGREEMENT_LEVELS = frozenset(
    {
        "STRONG_AGREEMENT",
        "MODERATE_AGREEMENT",
        "WEAK_AGREEMENT",
        "SPLIT",
        "INSUFFICIENT",
        "UNKNOWN",
    }
)
DISAGREEMENT_LEVELS = frozenset({"NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"})
INDEPENDENCE_STATUS = frozenset(
    {
        "INDEPENDENT",
        "PARTIALLY_DEPENDENT",
        "SAME_PROVIDER_FAMILY",
        "DUPLICATE",
        "UNKNOWN",
    }
)

MIN_MEMBERS = 2
MAX_MEMBERS = 5
MAX_BATCH_DETERMINISTIC = 100
MAX_BATCH_MOCK_SYNTHESIS = 50
MAX_BATCH_EXTERNAL_SYNTHESIS = 10

# Confidence caps
MAX_CONF_FAMILY_1 = 0.65
MAX_CONF_NO_REVIEW_MAJORITY = 0.70
MAX_CONF_UNSCORED = 0.70
MAX_CONF_MAJOR_DISAGREE = 0.55
MAX_CONF_CRITICAL_CONFLICT = 0.50
MAX_CONF_MOCK_ONLY = 0.60

SCORE_MIN = 0
SCORE_MAX = 100

FORBIDDEN_RESULT_KEYS = frozenset(
    {
        "buy",
        "sell",
        "hold",
        "recommendation",
        "recommended_action",
        "execute",
        "order",
        "submit_order",
        "target_price",
        "entry_price",
        "stop_loss",
        "take_profit",
        "position_size",
        "allocation",
        "rebalance",
        "candidate_approved",
        "candidate_rank",
        "strategy_id",
        "live",
        "arm",
        "runtime_resume",
        "scheduler_start",
        "api_key",
    }
)

PROVIDER_FAMILY_MAP = {
    "openai": "openai",
    "openai_compatible": "openai",
    "claude": "anthropic",
    "anthropic": "anthropic",
    "gemini": "google",
    "google": "google",
    "ollama": "ollama",
    "mock": "mock",
}

# Assessment에서 합의 멤버로 인정 가능한 상태
INCLUDABLE_ASSESSMENT_STATUSES = frozenset(
    {
        "VALIDATED",
        "VALIDATED_WITH_WARNINGS",
        "REVIEW_APPROVED",
    }
)

EXCLUDED_ASSESSMENT_STATUSES = frozenset(
    {
        "SUPERSEDED",
        "BLOCKED",
        "INVALID",
        "FAILED",
        "CANCELLED",
        "REVIEW_REJECTED",
    }
)

APPROVED_REVIEW_DECISIONS = frozenset({"APPROVED", "APPROVED_WITH_WARNINGS"})
