"""STEP 11-8 — Review / Benchmark constants."""

from __future__ import annotations

REVIEW_ENGINE_VERSION = "11.8.0"

SOURCE_TYPES = frozenset(
    {
        "NEWS",
        "DISCLOSURE",
        "CHART",
        "MARKET",
        "EXECUTION",
        "CANDIDATE_ASSESSMENT",
        "CANDIDATE_CONSENSUS",
    }
)

ASSIGNMENT_STATUS = frozenset(
    {
        "UNASSIGNED",
        "ASSIGNED",
        "IN_REVIEW",
        "COMPLETED",
        "CANCELLED",
        "EXPIRED",
    }
)

REVIEW_STATUS = frozenset(
    {"DRAFT", "SUBMITTED", "AMENDED", "WITHDRAWN"}
)

DECISION = frozenset(
    {
        "PENDING",
        "APPROVED",
        "APPROVED_WITH_WARNINGS",
        "REVISION_REQUESTED",
        "REJECTED",
        "NOT_REVIEWABLE",
    }
)

CONSENSUS = frozenset(
    {
        "CONSENSUS",
        "MINOR_DISAGREEMENT",
        "MAJOR_DISAGREEMENT",
        "MANAGER_REVIEW_REQUIRED",
        "INSUFFICIENT_REVIEWS",
    }
)

FINDING_TYPES = frozenset(
    {
        "FACTUAL_ERROR",
        "UNSUPPORTED_CLAIM",
        "CITATION_MISSING",
        "CITATION_MISMATCH",
        "NUMERIC_MISMATCH",
        "SYMBOL_MISMATCH",
        "ENTITY_MISMATCH",
        "TIMEFRAME_MISMATCH",
        "SOURCE_VERSION_MISMATCH",
        "OVERCONFIDENT",
        "UNDERCONFIDENT",
        "SCHEMA_WEAKNESS",
        "PROMPT_WEAKNESS",
        "POLICY_WARNING",
        "SAFETY_VIOLATION",
        "DATA_QUALITY_IGNORED",
        "IMPORTANT_FACT_OMITTED",
        "HALLUCINATION",
        "OTHER",
    }
)

SEVERITIES = frozenset({"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"})

SCORE_MIN = 0
SCORE_MAX = 5

# Decision thresholds (Core Safety — DB로 완전 해제 불가)
MIN_REVIEWERS_FOR_APPROVE = 1
MIN_AVG_OVERALL_APPROVE = 3.0
MIN_AVG_SAFETY_APPROVE = 3.0
MAJOR_DISAGREEMENT_SPREAD = 2.0  # overall score spread

# Benchmark caps
MAX_BENCHMARK_MOCK_ITEMS = 500
MAX_BENCHMARK_EXTERNAL_ITEMS = 20

# Permissions (seed)
AI_PERMISSIONS = (
    "AI_REVIEW_VIEW",
    "AI_REVIEW_ASSIGN",
    "AI_REVIEW_SUBMIT",
    "AI_REVIEW_DECIDE",
    "AI_DATASET_MANAGE",
    "AI_BENCHMARK_RUN",
    "AI_BENCHMARK_VIEW",
)

QUALITY_DISCLAIMER = (
    "AI 분석 품질 승인입니다. 매매 승인·주문 지시·후보/전략 반영이 아닙니다."
)

RUBRIC_WEIGHTS = {
    "correctness_score": 0.25,
    "relevance_score": 0.15,
    "completeness_score": 0.15,
    "citation_score": 0.15,
    "safety_score": 0.20,
    "clarity_score": 0.10,
}

REVIEWABLE_ANALYSIS_STATUSES = frozenset(
    {
        "VALIDATED_ANALYSIS",
        "VALIDATED_WITH_WARNINGS",
        "SUPERSEDED",  # 표시만 — Decision에서 NOT_REVIEWABLE 가능
        "BLOCKED",
        "INVALID",
        "FAILED",
    }
)
