"""STEP 12-3 §12 — 승인 직전 Structured Output 재검증.

STEP12-2-2의 검증기(`strategy_draft_generation.schema`)를 그대로 재사용한다
(중복 구현하지 않음). 다만 `StrategyDraftGenerationOutput`(AI 생성 시점
envelope 전체 — symbols/confidence/rationale 등 Draft 엔티티에 없는 필드도
요구)에 그대로 맞출 수는 없으므로, Draft가 실제로 저장하는 필드
(entry_rule/exit_rule/stop_loss_rule/take_profit_rule/position_sizing_rule/
market_type/timeframe)에 대응하는 하위 모델(DraftRule/StopLossRule/
TakeProfitRule/PositionSizingRule)과 화이트리스트 상수만 재사용해
검증한다 — 수동 Draft와 AI Draft 모두 동일하게 적용된다.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from stock_platform.ai.strategy_draft_generation.constants import (
    ALLOWED_MARKET_TYPES,
    ALLOWED_TIMEFRAMES,
)
from stock_platform.ai.strategy_draft_generation.schema import (
    DraftRule,
    PositionSizingRule,
    StopLossRule,
    TakeProfitRule,
)


class DraftApprovalValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _load_json(raw: str | None, *, field: str) -> Any:
    if raw is None or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DraftApprovalValidationError(
            "STRUCTURED_VALIDATION_FAILED", f"{field}: JSON 파싱 실패({exc})"
        ) from exc


def validate_draft_for_approval(draft: dict[str, Any]) -> None:
    """승인 가능 여부의 구조적 검증만 수행한다(존재/상태/fingerprint 등의
    조건은 서비스 레이어에서 별도로 검사). 실패 시 항상
    `DraftApprovalValidationError`를 발생시키고, 어떤 경우에도 누락된
    필드를 추측해 채우거나 깨진 데이터를 관대하게 복구하지 않는다."""

    market_type = (draft.get("market_type") or "").upper()
    if market_type not in ALLOWED_MARKET_TYPES:
        raise DraftApprovalValidationError(
            "STRUCTURED_VALIDATION_FAILED", f"허용되지 않은 market_type: {market_type}"
        )
    timeframe = draft.get("timeframe")
    if timeframe not in ALLOWED_TIMEFRAMES:
        raise DraftApprovalValidationError(
            "STRUCTURED_VALIDATION_FAILED", f"허용되지 않은 timeframe: {timeframe}"
        )

    entry_raw = _load_json(draft.get("entry_rule"), field="entry_rule")
    exit_raw = _load_json(draft.get("exit_rule"), field="exit_rule")
    stop_loss_raw = _load_json(draft.get("stop_loss_rule"), field="stop_loss_rule")
    take_profit_raw = _load_json(draft.get("take_profit_rule"), field="take_profit_rule")
    position_sizing_raw = _load_json(
        draft.get("position_sizing_rule"), field="position_sizing_rule"
    )

    if not entry_raw or not isinstance(entry_raw, list):
        raise DraftApprovalValidationError(
            "STRUCTURED_VALIDATION_FAILED", "entry_rule이 비어 있습니다."
        )
    if not exit_raw or not isinstance(exit_raw, list):
        raise DraftApprovalValidationError(
            "STRUCTURED_VALIDATION_FAILED", "exit_rule이 비어 있습니다."
        )
    if stop_loss_raw is None or take_profit_raw is None or position_sizing_raw is None:
        raise DraftApprovalValidationError(
            "STRUCTURED_VALIDATION_FAILED",
            "stop_loss_rule/take_profit_rule/position_sizing_rule은 필수입니다.",
        )

    try:
        entry_rules = [DraftRule.model_validate(item) for item in entry_raw]
        exit_rules = [DraftRule.model_validate(item) for item in exit_raw]
        stop_loss = StopLossRule.model_validate(stop_loss_raw)
        take_profit = TakeProfitRule.model_validate(take_profit_raw)
        position_sizing = PositionSizingRule.model_validate(position_sizing_raw)
    except ValidationError as exc:
        raise DraftApprovalValidationError(
            "STRUCTURED_VALIDATION_FAILED", f"Rule 검증 실패: {exc}"
        ) from exc

    # schema.py의 StrategyDraftGenerationOutput._cross_field_checks와 동일한
    # entry/exit 규칙 완전 동일 검사(모순 규칙 방지) — 그 검증기는 envelope
    # 전체를 요구해 재사용할 수 없으므로 동일한 규칙만 그대로 반영한다.
    entry_keys = {(r.indicator, r.operator, r.threshold) for r in entry_rules}
    exit_keys = {(r.indicator, r.operator, r.threshold) for r in exit_rules}
    if entry_keys and entry_keys == exit_keys:
        raise DraftApprovalValidationError(
            "STRUCTURED_VALIDATION_FAILED",
            "entry_rule과 exit_rule이 동일합니다(모순 규칙).",
        )

    indicator_config = draft.get("indicator_configuration") or {}
    if not isinstance(indicator_config, dict):
        raise DraftApprovalValidationError(
            "STRUCTURED_VALIDATION_FAILED", "indicator_configuration 형식이 올바르지 않습니다."
        )

    risk_parameters = draft.get("risk_parameters")
    if risk_parameters is not None:
        if not isinstance(risk_parameters, dict):
            raise DraftApprovalValidationError(
                "STRUCTURED_VALIDATION_FAILED", "risk_parameters 형식이 올바르지 않습니다."
            )
        for key, value in risk_parameters.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise DraftApprovalValidationError(
                    "STRUCTURED_VALIDATION_FAILED",
                    f"risk_parameters.{key}는 숫자여야 합니다.",
                )
            if value != value or value in (float("inf"), float("-inf")):
                raise DraftApprovalValidationError(
                    "STRUCTURED_VALIDATION_FAILED",
                    f"risk_parameters.{key}가 NaN/Infinity입니다.",
                )
