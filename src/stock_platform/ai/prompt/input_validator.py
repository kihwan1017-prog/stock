"""STEP 11-4 — 입력 변수 검증."""

from __future__ import annotations

from typing import Any

from stock_platform.ai.prompt.injection import has_control_chars, inspect_text_security
from stock_platform.ai.prompt.task_types import MAX_CONTEXT_CHARS


class AIInputValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_variables(
    variables: dict[str, Any],
    variable_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Variable Schema 기반 검증. 미정의 키 Fail Closed."""

    schema = variable_schema or {}
    properties = schema.get("properties") or {}
    required = list(schema.get("required") or [])
    additional = bool(schema.get("additionalProperties", False))

    if not isinstance(variables, dict):
        raise AIInputValidationError("INVALID_INPUT", "variables must be object")

    for key in variables:
        if key not in properties and not additional:
            raise AIInputValidationError(
                "UNDEFINED_VARIABLE",
                f"Variable not in schema: {key}",
            )

    for key in required:
        if key not in variables:
            raise AIInputValidationError(
                "MISSING_VARIABLE",
                f"Required variable missing: {key}",
            )

    warnings: list[str] = []
    for key, value in variables.items():
        prop = properties.get(key) or {}
        expected = prop.get("type")
        if expected == "string" and not isinstance(value, str):
            raise AIInputValidationError(
                "TYPE_ERROR", f"{key} must be string"
            )
        if expected == "number" and not isinstance(value, (int, float)):
            raise AIInputValidationError(
                "TYPE_ERROR", f"{key} must be number"
            )
        if expected == "object" and not isinstance(value, dict):
            raise AIInputValidationError(
                "TYPE_ERROR", f"{key} must be object"
            )
        if expected == "array" and not isinstance(value, list):
            raise AIInputValidationError(
                "TYPE_ERROR", f"{key} must be array"
            )
        text = value if isinstance(value, str) else str(value)
        if len(text) > MAX_CONTEXT_CHARS:
            raise AIInputValidationError(
                "INPUT_TOO_LARGE", f"{key} too large"
            )
        if isinstance(value, str) and has_control_chars(value):
            raise AIInputValidationError(
                "CONTROL_CHARS", f"{key} contains control characters"
            )
        sec = inspect_text_security(text)
        if sec["blocked"]:
            raise AIInputValidationError(
                "INPUT_POLICY_BLOCKED",
                f"{key} failed security inspection",
            )
        if sec["pii_detected"]:
            warnings.append(f"PII in {key}: {','.join(sec['pii_detected'])}")

    return {"ok": True, "warnings": warnings}
