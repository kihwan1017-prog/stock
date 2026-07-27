"""STEP 11-4 — AI Task Type 정의 (업무 실행 없음)."""

from __future__ import annotations

from enum import StrEnum


class AITaskType(StrEnum):
    CHAT = "CHAT"
    SUMMARIZE = "SUMMARIZE"
    NEWS_ANALYSIS = "NEWS_ANALYSIS"
    DISCLOSURE_ANALYSIS = "DISCLOSURE_ANALYSIS"
    CHART_ANALYSIS = "CHART_ANALYSIS"
    MARKET_ANALYSIS = "MARKET_ANALYSIS"
    STOCK_CANDIDATE_ANALYSIS = "STOCK_CANDIDATE_ANALYSIS"
    CRYPTO_CANDIDATE_ANALYSIS = "CRYPTO_CANDIDATE_ANALYSIS"
    STOCK_CANDIDATE_CONSENSUS = "STOCK_CANDIDATE_CONSENSUS"
    CRYPTO_CANDIDATE_CONSENSUS = "CRYPTO_CANDIDATE_CONSENSUS"
    STRATEGY_DRAFT = "STRATEGY_DRAFT"
    STRATEGY_REVIEW = "STRATEGY_REVIEW"
    RISK_REVIEW = "RISK_REVIEW"
    PORTFOLIO_REVIEW = "PORTFOLIO_REVIEW"


TASK_TYPES = frozenset(t.value for t in AITaskType)

TEMPLATE_STATUSES = frozenset({"DRAFT", "ACTIVE", "INACTIVE", "ARCHIVED"})
SCHEMA_STATUSES = frozenset({"DRAFT", "ACTIVE", "INACTIVE", "ARCHIVED"})
POLICY_STATUSES = frozenset({"DRAFT", "ACTIVE", "INACTIVE", "ARCHIVED"})
POLICY_TYPES = frozenset(
    {
        "TRADING_SAFETY",
        "OUTPUT_SAFETY",
        "FINANCIAL_GUARDRAIL",
        "DATA_SECURITY",
        "PROMPT_SECURITY",
    }
)
ENFORCEMENT_MODES = frozenset({"BLOCK", "WARN", "AUDIT_ONLY"})

# Strategy Draft / 출력에 절대 허용하지 않는 필드
FORBIDDEN_OUTPUT_FIELDS = frozenset(
    {
        "execute",
        "submit_order",
        "live",
        "arm",
        "scheduler_start",
        "runtime_resume",
        "api_key",
        "account_password",
        "broker_token",
        "kill_switch_off",
        "credential",
    }
)

MAX_PROMPT_CHARS = 50_000
MAX_CONTEXT_CHARS = 30_000
MAX_RESPONSE_CHARS = 100_000
MAX_NESTING_DEPTH = 12
MAX_ARRAY_ITEMS = 200
