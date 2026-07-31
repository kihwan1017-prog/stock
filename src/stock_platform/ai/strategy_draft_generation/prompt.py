"""STEP 12-2-2 — Strategy Draft 생성 Prompt (버전 가능, 코드에 산재 금지).

`ai.prompt` 패키지(STEP 11-4)의 기존 렌더러/파서/검증기를 그대로 재사용한다.
템플릿 문자열 자체는 이 모듈에 버전별로 보존하고, DB의
`ai.prompt_template`/`ai.prompt_template_version`/`ai.output_schema`
(신규 Migration에서 seed)에 checksum과 함께 등록해 재현 가능성을 보장한다.
"""

from __future__ import annotations

import json
from typing import Any

from stock_platform.ai.prompt.renderer import checksum_text, render_template
from stock_platform.ai.prompt.seed_data import envelope
from stock_platform.ai.prompt.task_types import AITaskType
from stock_platform.ai.strategy_draft_generation.constants import (
    ALLOWED_INDICATORS,
    ALLOWED_MARKET_TYPES,
    ALLOWED_OPERATORS,
    ALLOWED_POSITION_SIZING_METHODS,
    ALLOWED_STOP_LOSS_TYPES,
    ALLOWED_TAKE_PROFIT_TYPES,
    ALLOWED_TIMEFRAMES,
    MAX_POSITION_SIZE_PERCENT,
    MAX_STOP_LOSS_PERCENT,
    MAX_TAKE_PROFIT_PERCENT,
    PROMPT_TEMPLATE_CODE,
)

PROMPT_TEMPLATE_VERSION = 1

SYSTEM_TEMPLATE_V1 = (
    "task_type: STRATEGY_DRAFT\n"
    "You are a trading strategy drafting assistant for a review-only pipeline. "
    "You draft a STRUCTURED strategy sketch for a human reviewer. "
    "You NEVER place orders, enable live trading, arm/resume runtime or "
    "scheduler, or reveal credentials/secrets. "
    "Rules:\n"
    "1. Do not invent facts not present in the provided evidence.\n"
    "2. Only use indicators from this whitelist: {{allowed_indicators}}.\n"
    "3. Only use comparison operators from this whitelist: {{allowed_operators}}.\n"
    "4. Output structured rules, not vague prose.\n"
    "5. Always include stop_loss_rule, take_profit_rule, and "
    "position_sizing_rule — never omit them.\n"
    "6. If uncertain about any fact, list it under assumptions or warnings "
    "instead of guessing.\n"
    "7. Clearly separate explanatory text (summary/rationale) from "
    "executable rules (entry_rules/exit_rules/etc).\n"
    "8. Respond with a single JSON object only, matching the schema below. "
    "No markdown, no extra commentary outside the JSON.\n"
    "9. stop_loss_rule.value and take_profit_rule.value are POSITIVE "
    "magnitudes only (distance from entry as a percent or ATR multiple) — "
    "never a negative number, even for a stop loss."
)

USER_TEMPLATE_V1 = (
    "candidate_id={{candidate_id}}\n"
    "market_type={{market_type}}\n"
    "allowed_market_types={{allowed_market_types}}\n"
    "symbol={{symbol}}\n"
    "timeframe_hint={{timeframe_hint}}\n"
    "allowed_timeframes={{allowed_timeframes}}\n\n"
    "candidate_evidence:\n{{candidate_evidence}}\n\n"
    "signals_and_scores:\n{{signals_and_scores}}\n\n"
    "candidate_provenance:\n{{candidate_provenance}}\n\n"
    "risk_limits:\n{{risk_limits}}\n\n"
    "output_schema:\n{{output_schema}}\n\n"
    "Produce the strategy draft JSON now."
)

_ALLOWED_KEYS = {
    "allowed_indicators",
    "allowed_operators",
    "allowed_market_types",
    "allowed_timeframes",
    "candidate_id",
    "market_type",
    "symbol",
    "timeframe_hint",
    "candidate_evidence",
    "signals_and_scores",
    "candidate_provenance",
    "risk_limits",
    "output_schema",
}

# STEP12-2-3A: Ollama structured-output(format=JSON Schema) 및 프롬프트에
# 그대로 노출되는 중첩 규칙 스키마 — schema.py의 Pydantic
# DraftRule/StopLossRule/TakeProfitRule/PositionSizingRule과 필드/제약을
# 일치시킨다(모델이 추측하지 않고 정확한 형태를 그대로 따르게 하기 위함).
_DRAFT_RULE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["indicator", "operator", "threshold"],
    "properties": {
        "indicator": {"type": "string", "enum": sorted(ALLOWED_INDICATORS)},
        "operator": {"type": "string", "enum": sorted(ALLOWED_OPERATORS)},
        "threshold": {"type": "number"},
        "comparison_target": {"type": "string", "maxLength": 100},
        "timeframe": {"type": "string", "maxLength": 20},
        "lookback": {"type": "integer", "minimum": 1, "maximum": 500},
        "confirmation_count": {"type": "integer", "minimum": 1, "maximum": 10},
    },
}

_STOP_LOSS_RULE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "value"],
    "properties": {
        "type": {"type": "string", "enum": sorted(ALLOWED_STOP_LOSS_TYPES)},
        "value": {
            "type": "number",
            "minimum": 0,
            "maximum": MAX_STOP_LOSS_PERCENT,
            "description": "Positive magnitude only (never negative).",
        },
    },
}

_TAKE_PROFIT_RULE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "value"],
    "properties": {
        "type": {"type": "string", "enum": sorted(ALLOWED_TAKE_PROFIT_TYPES)},
        "value": {
            "type": "number",
            "minimum": 0,
            "maximum": MAX_TAKE_PROFIT_PERCENT,
            "description": "Positive magnitude only (never negative).",
        },
    },
}

_POSITION_SIZING_RULE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["method", "value"],
    "properties": {
        "method": {
            "type": "string",
            "enum": sorted(ALLOWED_POSITION_SIZING_METHODS),
        },
        "value": {
            "type": "number",
            "minimum": 0,
            "maximum": MAX_POSITION_SIZE_PERCENT,
        },
    },
}

STRATEGY_DRAFT_RESULT_PROPS: dict[str, Any] = {
    "title": {"type": "string", "maxLength": 200},
    # STEP12-2-3A: 실측 결과 Ollama(0.32.4)의 JSON Schema -> grammar 컴파일러가
    # maxLength>=~2000인 string 속성에서 "failed to parse grammar"로 400을
    # 반환한다(1992는 통과, 2000은 실패 — 실제 curl로 이진 탐색해 확인). 이
    # 필드에 한해 스키마 상한을 1900으로 낮춘다(Pydantic MAX_STRING_FIELD_CHARS
    # =2000은 그대로 두어 여전히 더 엄격한 상한으로 작동한다).
    "summary": {"type": "string", "maxLength": 1900},
    "market_type": {"type": "string", "enum": sorted(ALLOWED_MARKET_TYPES)},
    "symbols": {
        "type": "array",
        "maxItems": 20,
        "items": {"type": "string", "maxLength": 40},
    },
    "timeframe": {"type": "string", "enum": sorted(ALLOWED_TIMEFRAMES)},
    "entry_rules": {
        "type": "array",
        "minItems": 1,
        "maxItems": 10,
        "items": _DRAFT_RULE_ITEM_SCHEMA,
    },
    "exit_rules": {
        "type": "array",
        "minItems": 1,
        "maxItems": 10,
        "items": _DRAFT_RULE_ITEM_SCHEMA,
    },
    "stop_loss_rule": _STOP_LOSS_RULE_SCHEMA,
    "take_profit_rule": _TAKE_PROFIT_RULE_SCHEMA,
    "position_sizing_rule": _POSITION_SIZING_RULE_SCHEMA,
    "indicators": {
        "type": "array",
        "maxItems": 20,
        "items": {"type": "string", "enum": sorted(ALLOWED_INDICATORS)},
    },
    "risk_parameters": {"type": "object"},
    "trading_session_rules": {"type": "array", "maxItems": 20},
    "cooldown_rules": {"type": "array", "maxItems": 20},
    "invalidation_conditions": {"type": "array", "maxItems": 20},
    "assumptions": {"type": "array", "maxItems": 20},
    "warnings": {"type": "array", "maxItems": 20},
    "rationale": {"type": "string", "maxLength": 1900},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
}

# schema.py의 Pydantic StrategyDraftGenerationOutput에서 default가 없는
# (필수) 필드와 정확히 일치시킨다 — Ollama 등 grammar 제약 Provider가
# 이 필드들을 건너뛰고 조기에 JSON 객체를 닫는 것을 스키마 차원에서
# 막는다(§STEP12-2-3A: required 없이는 실측상 title/summary/market_type
# 등 일부만 채우고 조기 종료하는 사례가 재현됐다).
_STRATEGY_DRAFT_RESULT_REQUIRED = [
    "title",
    "summary",
    "market_type",
    "symbols",
    "timeframe",
    "entry_rules",
    "exit_rules",
    "stop_loss_rule",
    "take_profit_rule",
    "position_sizing_rule",
    "confidence",
    "rationale",
]

# validate_ai_output()에 넘길 envelope 스키마 — generic 1차 검증용.
STRATEGY_DRAFT_OUTPUT_ENVELOPE = envelope(
    AITaskType.STRATEGY_DRAFT.value,
    STRATEGY_DRAFT_RESULT_PROPS,
    result_required=_STRATEGY_DRAFT_RESULT_REQUIRED,
)
# STEP12-2-3A: 공통 envelope(COMMON_ENVELOPE_PROPS, ai/prompt/seed_data.py)의
# reasoning_summary도 maxLength=2000이라 동일한 Ollama grammar 컴파일 실패를
# 유발한다. 다른 task_type이 공유하는 seed_data.py는 건드리지 않고, 이
# 도메인의 envelope 사본에서만 상한을 낮춘다.
STRATEGY_DRAFT_OUTPUT_ENVELOPE["properties"]["reasoning_summary"]["maxLength"] = 1900


def prompt_template_checksum() -> str:
    return checksum_text(SYSTEM_TEMPLATE_V1, USER_TEMPLATE_V1, PROMPT_TEMPLATE_CODE)


def build_prompt_variables(
    *,
    candidate_id: int,
    market_type: str,
    symbol: str,
    timeframe_hint: str,
    candidate_evidence: dict[str, Any],
    signals_and_scores: dict[str, Any],
    candidate_provenance: dict[str, Any],
    risk_limits: dict[str, Any],
) -> dict[str, Any]:
    return {
        "allowed_indicators": ", ".join(sorted(ALLOWED_INDICATORS)),
        "allowed_operators": ", ".join(sorted(ALLOWED_OPERATORS)),
        "allowed_market_types": ", ".join(sorted(ALLOWED_MARKET_TYPES)),
        "allowed_timeframes": ", ".join(sorted(ALLOWED_TIMEFRAMES)),
        "candidate_id": candidate_id,
        "market_type": market_type,
        "symbol": symbol,
        "timeframe_hint": timeframe_hint,
        "candidate_evidence": candidate_evidence,
        "signals_and_scores": signals_and_scores,
        "candidate_provenance": candidate_provenance,
        "risk_limits": risk_limits,
        "output_schema": STRATEGY_DRAFT_RESULT_PROPS,
    }


def render_system_prompt(
    variables: dict[str, Any], *, system_template: str = SYSTEM_TEMPLATE_V1
) -> str:
    return render_template(
        system_template, variables, allowed_keys=_ALLOWED_KEYS, field="system"
    )


def render_user_prompt(
    variables: dict[str, Any], *, user_template: str = USER_TEMPLATE_V1
) -> str:
    return render_template(
        user_template, variables, allowed_keys=_ALLOWED_KEYS, field="user"
    )


__all__ = [
    "PROMPT_TEMPLATE_VERSION",
    "SYSTEM_TEMPLATE_V1",
    "USER_TEMPLATE_V1",
    "STRATEGY_DRAFT_OUTPUT_ENVELOPE",
    "STRATEGY_DRAFT_RESULT_PROPS",
    "prompt_template_checksum",
    "build_prompt_variables",
    "render_system_prompt",
    "render_user_prompt",
]
