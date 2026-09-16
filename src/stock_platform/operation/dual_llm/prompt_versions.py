"""Market-aware prompt / schema versioning for Dual LLM research."""

from __future__ import annotations

from stock_platform.operation.dual_llm.markets import MARKET_KIWOOM, MARKET_UPBIT

# Common dual schema (market field required in payload)
SCHEMA_DUAL_COMMON_V1 = "dual_llm_rag_v1"

# Legacy UPBIT-only schemas (still readable)
SCHEMA_UPBIT_DUAL_V1 = "upbit_dual_llm_shadow_v1"
SCHEMA_UPBIT_RAG_V1 = "upbit_dual_llm_rag_v1"
SCHEMA_KIWOOM_RAG_V1 = "kiwoom_dual_llm_rag_v1"

DUAL_SCHEMA_VERSIONS = frozenset(
    {
        SCHEMA_DUAL_COMMON_V1,
        SCHEMA_UPBIT_DUAL_V1,
        SCHEMA_UPBIT_RAG_V1,
        SCHEMA_KIWOOM_RAG_V1,
    }
)

# Market-aware prompts — overwrite 금지, 새 버전만 추가
ANALYSIS_UPBIT_PROMPT_V1 = "analysis_upbit_prompt_v1"
TRADING_UPBIT_PROMPT_V1 = "trading_upbit_prompt_v1"
TRADING_UPBIT_PROMPT_V2 = "trading_upbit_prompt_v2"
TEACHER_UPBIT_PROMPT_V1 = "teacher_upbit_prompt_v1"

ANALYSIS_KIWOOM_PROMPT_V1 = "analysis_kiwoom_prompt_v1"
TRADING_KIWOOM_PROMPT_V1 = "trading_kiwoom_prompt_v1"
TEACHER_KIWOOM_PROMPT_V1 = "teacher_kiwoom_prompt_v1"

# Backward-compatible aliases (UPBIT legacy names)
ANALYSIS_PROMPT_VERSION = ANALYSIS_UPBIT_PROMPT_V1
TRADING_PROMPT_VERSION = TRADING_UPBIT_PROMPT_V2
TEACHER_PROMPT_VERSION = TEACHER_UPBIT_PROMPT_V1
SCHEMA_RAG_V1 = SCHEMA_UPBIT_RAG_V1
SCHEMA_DUAL_V1 = SCHEMA_UPBIT_DUAL_V1


def is_dual_llm_schema(version: object) -> bool:
    return str(version or "") in DUAL_SCHEMA_VERSIONS


def prompt_versions_for(market: str) -> dict[str, str]:
    m = str(market or "").upper()
    if m == MARKET_KIWOOM:
        return {
            "analysis": ANALYSIS_KIWOOM_PROMPT_V1,
            "trading": TRADING_KIWOOM_PROMPT_V1,
            "teacher": TEACHER_KIWOOM_PROMPT_V1,
        }
    return {
        "analysis": ANALYSIS_UPBIT_PROMPT_V1,
        "trading": TRADING_UPBIT_PROMPT_V2,
        "teacher": TEACHER_UPBIT_PROMPT_V1,
    }


def schema_for(market: str) -> str:
    m = str(market or "").upper()
    if m == MARKET_KIWOOM:
        return SCHEMA_KIWOOM_RAG_V1
    if m == MARKET_UPBIT:
        return SCHEMA_UPBIT_RAG_V1
    return SCHEMA_DUAL_COMMON_V1


def settings_fingerprint(
    *,
    model: str,
    role: str,
    temperature: float,
    max_tokens: int,
    prompt_version: str,
    market: str | None = None,
) -> str:
    base = (
        f"{role}|{model}|t={temperature:.3f}|n={int(max_tokens)}|{prompt_version}"
    )
    if market:
        return f"{base}|m={str(market).upper()}"
    return base
