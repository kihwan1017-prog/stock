"""UPBIT prompt version re-exports — prefer dual_llm.prompt_versions for new code."""

from __future__ import annotations

from stock_platform.operation.dual_llm.prompt_versions import (  # noqa: F401
    ANALYSIS_PROMPT_VERSION,
    ANALYSIS_UPBIT_PROMPT_V1 as ANALYSIS_PROMPT_VERSION_MARKET,
    DUAL_SCHEMA_VERSIONS,
    SCHEMA_DUAL_V1,
    SCHEMA_RAG_V1,
    SCHEMA_UPBIT_RAG_V1,
    TEACHER_PROMPT_VERSION,
    TRADING_PROMPT_VERSION,
    is_dual_llm_schema,
    settings_fingerprint,
)

__all__ = [
    "ANALYSIS_PROMPT_VERSION",
    "TRADING_PROMPT_VERSION",
    "TEACHER_PROMPT_VERSION",
    "SCHEMA_DUAL_V1",
    "SCHEMA_RAG_V1",
    "DUAL_SCHEMA_VERSIONS",
    "is_dual_llm_schema",
    "settings_fingerprint",
]
