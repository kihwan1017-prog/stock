"""LLM input/output schemas — research only, no order generation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from stock_platform.operation.upbit_market_context.constants import (
    LLM_RECOMMENDATIONS,
    RISK_FLAG_ENUM,
)


class LlmContextInput(BaseModel):
    """구조화 LLM 입력 — candidate detected_at 이전 context만."""

    schema_version: str = "upbit_llm_entry_context_v1"
    context_as_of: str
    candidate: dict[str, Any]
    technical: dict[str, Any] = Field(default_factory=dict)
    market_context: dict[str, Any] = Field(default_factory=dict)
    asset_context: dict[str, Any] = Field(default_factory=dict)
    execution_strength: dict[str, Any] = Field(default_factory=dict)
    returns: dict[str, Any] = Field(default_factory=dict)
    news: list[dict[str, Any]] = Field(default_factory=list)
    asset_description: dict[str, Any] = Field(default_factory=dict)
    research_only: bool = True
    may_create_orders: bool = False


class LlmContextOutput(BaseModel):
    """LLM 출력 — ALLOW/HOLD/REDUCE only. 주문 생성 금지."""

    schema_version: str = "upbit_llm_entry_quality_v1"
    recommendation: Literal["ALLOW", "HOLD", "REDUCE"]
    confidence: float = Field(ge=0.0, le=1.0)
    entry_quality_score: int = Field(ge=0, le=100)
    risk_flags: list[str] = Field(default_factory=list)
    positive_factors: list[str] = Field(default_factory=list)
    negative_factors: list[str] = Field(default_factory=list)
    short_reason_ko: str = ""
    context_unavailable: bool = False

    @field_validator("recommendation")
    @classmethod
    def _rec(cls, v: str) -> str:
        u = str(v or "").upper()
        if u not in LLM_RECOMMENDATIONS:
            raise ValueError(f"invalid recommendation: {v}")
        return u

    @field_validator("risk_flags")
    @classmethod
    def _flags(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for item in v or []:
            key = str(item or "").upper()
            if key in RISK_FLAG_ENUM:
                out.append(key)
        return out


def fail_open_output(*, reason: str) -> LlmContextOutput:
    """LLM/데이터 실패 시 research fail-open — REAL block 금지."""

    return LlmContextOutput(
        recommendation="HOLD",
        confidence=0.0,
        entry_quality_score=50,
        risk_flags=["CONTEXT_UNAVAILABLE"],
        positive_factors=[],
        negative_factors=[reason[:120]],
        short_reason_ko=f"컨텍스트 없음: {reason[:80]}",
        context_unavailable=True,
    )


def parse_llm_output(raw: dict[str, Any] | None) -> LlmContextOutput:
    if not isinstance(raw, dict):
        return fail_open_output(reason="EMPTY_LLM_RESPONSE")
    try:
        return LlmContextOutput.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        return fail_open_output(reason=f"SCHEMA_INVALID:{type(exc).__name__}")


LLM_INPUT_SCHEMA_DOC = {
    "schema": "upbit_llm_entry_context_v1",
    "fields": [
        "candidate",
        "technical",
        "market_context",
        "asset_context",
        "execution_strength",
        "returns",
        "news",
        "asset_description",
        "context_as_of",
    ],
    "constraints": [
        "context timestamps <= detected_at",
        "research_only=true",
        "may_create_orders=false",
    ],
}

LLM_OUTPUT_SCHEMA_DOC = {
    "schema": "upbit_llm_entry_quality_v1",
    "recommendation": sorted(LLM_RECOMMENDATIONS),
    "entry_quality_score": "0..100",
    "risk_flags": sorted(RISK_FLAG_ENUM),
    "fields": [
        "confidence",
        "positive_factors",
        "negative_factors",
        "short_reason_ko",
    ],
}
