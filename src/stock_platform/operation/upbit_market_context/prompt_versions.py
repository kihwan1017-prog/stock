"""Dual LLM prompt / model versioning — overwrite 금지, record만 증가.

과거 prediction과 새 prompt를 구분하기 위해 version 문자열을 고정 보관한다.
"""

from __future__ import annotations

# 역할별 prompt version — 변경 시 새 상수 추가 후 코드에서 참조 전환
ANALYSIS_PROMPT_VERSION = "analysis_prompt_v1"
TRADING_PROMPT_VERSION = "trading_prompt_v1"
TEACHER_PROMPT_VERSION = "teacher_prompt_v1"

SCHEMA_DUAL_V1 = "upbit_dual_llm_shadow_v1"
SCHEMA_RAG_V1 = "upbit_dual_llm_rag_v1"

DUAL_SCHEMA_VERSIONS = frozenset({SCHEMA_DUAL_V1, SCHEMA_RAG_V1})


def is_dual_llm_schema(version: object) -> bool:
    return str(version or "") in DUAL_SCHEMA_VERSIONS


def settings_fingerprint(
    *,
    model: str,
    role: str,
    temperature: float,
    max_tokens: int,
    prompt_version: str,
) -> str:
    """설정 지문 — LoRA/모델 비교용 (비밀값 미포함)."""

    return (
        f"{role}|{model}|t={temperature:.3f}|n={int(max_tokens)}|{prompt_version}"
    )
