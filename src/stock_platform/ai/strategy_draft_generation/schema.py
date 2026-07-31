"""STEP 12-2-2 — Structured Output Schema (Pydantic 엄격 검증).

AI 응답을 자유 형식 문자열로 바로 Strategy Draft에 저장하지 않는다.
generic 파이프라인(`ai.prompt.output_validator.validate_ai_output` — JSON
파싱/시크릿·PII/Core Safety/금지 필드/봉투 JSON Schema)을 1차로 통과한
`result` payload만 이 모듈에서 2차로 엄격 검증한다(indicator/operator
화이트리스트, risk 상한, entry/exit 모순 등 도메인 특화 규칙).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from stock_platform.ai.strategy_draft_generation.constants import (
    ALLOWED_INDICATORS,
    ALLOWED_MARKET_TYPES,
    ALLOWED_OPERATORS,
    ALLOWED_POSITION_SIZING_METHODS,
    ALLOWED_STOP_LOSS_TYPES,
    ALLOWED_TAKE_PROFIT_TYPES,
    ALLOWED_TIMEFRAMES,
    MAX_POSITION_SIZE_PERCENT,
    MAX_RULES_PER_SIDE,
    MAX_STOP_LOSS_PERCENT,
    MAX_STRING_FIELD_CHARS,
    MAX_SYMBOLS,
    MAX_TAKE_PROFIT_PERCENT,
)


class GenerationSchemaError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _finite(v: float, *, field: str) -> float:
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"{field} must be finite")
    return v


class DraftRule(BaseModel):
    model_config = {"extra": "forbid"}

    indicator: str
    operator: str
    threshold: float
    comparison_target: str | None = Field(default=None, max_length=100)
    timeframe: str | None = Field(default=None, max_length=20)
    lookback: int | None = Field(default=None, ge=1, le=500)
    confirmation_count: int | None = Field(default=None, ge=1, le=10)

    @field_validator("indicator")
    @classmethod
    def _indicator_allowed(cls, v: str) -> str:
        upper = v.upper()
        if upper not in ALLOWED_INDICATORS:
            raise ValueError(f"unknown indicator: {v}")
        return upper

    @field_validator("operator")
    @classmethod
    def _operator_allowed(cls, v: str) -> str:
        upper = v.upper()
        if upper not in ALLOWED_OPERATORS:
            raise ValueError(f"unknown operator: {v}")
        return upper

    @field_validator("threshold")
    @classmethod
    def _threshold_finite(cls, v: float) -> float:
        return _finite(v, field="threshold")


class StopLossRule(BaseModel):
    model_config = {"extra": "forbid"}

    type: str
    value: float

    @field_validator("type")
    @classmethod
    def _type_allowed(cls, v: str) -> str:
        upper = v.upper()
        if upper not in ALLOWED_STOP_LOSS_TYPES:
            raise ValueError(f"unknown stop_loss type: {v}")
        return upper

    @field_validator("value")
    @classmethod
    def _value_bounds(cls, v: float) -> float:
        v = _finite(v, field="stop_loss_rule.value")
        if not (0 < v <= MAX_STOP_LOSS_PERCENT):
            raise ValueError(
                f"stop_loss value out of range (0, {MAX_STOP_LOSS_PERCENT}]"
            )
        return v


class TakeProfitRule(BaseModel):
    model_config = {"extra": "forbid"}

    type: str
    value: float

    @field_validator("type")
    @classmethod
    def _type_allowed(cls, v: str) -> str:
        upper = v.upper()
        if upper not in ALLOWED_TAKE_PROFIT_TYPES:
            raise ValueError(f"unknown take_profit type: {v}")
        return upper

    @field_validator("value")
    @classmethod
    def _value_bounds(cls, v: float) -> float:
        v = _finite(v, field="take_profit_rule.value")
        if not (0 < v <= MAX_TAKE_PROFIT_PERCENT):
            raise ValueError(
                f"take_profit value out of range (0, {MAX_TAKE_PROFIT_PERCENT}]"
            )
        return v


class PositionSizingRule(BaseModel):
    model_config = {"extra": "forbid"}

    method: str
    value: float

    @field_validator("method")
    @classmethod
    def _method_allowed(cls, v: str) -> str:
        upper = v.upper()
        if upper not in ALLOWED_POSITION_SIZING_METHODS:
            raise ValueError(f"unknown position sizing method: {v}")
        return upper

    @field_validator("value")
    @classmethod
    def _value_bounds(cls, v: float) -> float:
        v = _finite(v, field="position_sizing_rule.value")
        if not (0 < v <= MAX_POSITION_SIZE_PERCENT):
            raise ValueError(
                "position sizing value out of range "
                f"(0, {MAX_POSITION_SIZE_PERCENT}]"
            )
        return v


class StrategyDraftGenerationOutput(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=MAX_STRING_FIELD_CHARS)
    market_type: str
    symbols: list[str] = Field(min_length=1, max_length=MAX_SYMBOLS)
    timeframe: str
    entry_rules: list[DraftRule] = Field(min_length=1, max_length=MAX_RULES_PER_SIDE)
    exit_rules: list[DraftRule] = Field(min_length=1, max_length=MAX_RULES_PER_SIDE)
    stop_loss_rule: StopLossRule
    take_profit_rule: TakeProfitRule
    position_sizing_rule: PositionSizingRule
    indicators: list[str] = Field(default_factory=list, max_length=20)
    risk_parameters: dict[str, float] = Field(default_factory=dict)
    trading_session_rules: list[str] = Field(default_factory=list, max_length=20)
    cooldown_rules: list[str] = Field(default_factory=list, max_length=20)
    invalidation_conditions: list[str] = Field(default_factory=list, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=MAX_STRING_FIELD_CHARS)

    @field_validator("market_type")
    @classmethod
    def _market_type_allowed(cls, v: str) -> str:
        upper = v.upper()
        if upper not in ALLOWED_MARKET_TYPES:
            raise ValueError(f"unknown market_type: {v}")
        return upper

    @field_validator("timeframe")
    @classmethod
    def _timeframe_allowed(cls, v: str) -> str:
        if v not in ALLOWED_TIMEFRAMES:
            raise ValueError(f"unknown timeframe: {v}")
        return v

    @field_validator("indicators")
    @classmethod
    def _indicators_allowed(cls, v: list[str]) -> list[str]:
        upper = [i.upper() for i in v]
        unknown = sorted(set(upper) - ALLOWED_INDICATORS)
        if unknown:
            raise ValueError(f"unknown indicators: {unknown}")
        return upper

    @field_validator("risk_parameters")
    @classmethod
    def _risk_parameters_finite(cls, v: dict[str, Any]) -> dict[str, float]:
        result: dict[str, float] = {}
        for key, value in v.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"risk_parameters.{key} must be numeric")
            result[key] = _finite(float(value), field=f"risk_parameters.{key}")
        return result

    @model_validator(mode="after")
    def _cross_field_checks(self) -> "StrategyDraftGenerationOutput":
        # entry/exit 규칙 집합이 완전히 동일하면 모순으로 간주(최소 기준).
        entry_keys = {(r.indicator, r.operator, r.threshold) for r in self.entry_rules}
        exit_keys = {(r.indicator, r.operator, r.threshold) for r in self.exit_rules}
        if entry_keys and entry_keys == exit_keys:
            raise ValueError(
                "entry_rules and exit_rules are identical (contradiction)"
            )
        return self


def parse_and_validate_output(data: dict[str, Any]) -> StrategyDraftGenerationOutput:
    """1차(generic) 검증을 통과한 result payload에 대한 2차(도메인) 검증.

    실패 시 GenerationSchemaError — 이 경우 Strategy Draft/Version은
    생성하지 않는다.
    """
    try:
        return StrategyDraftGenerationOutput.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError 등
        raise GenerationSchemaError(
            "AI_OUTPUT_SCHEMA_INVALID",
            f"Structured output validation failed: {exc}",
        ) from exc
