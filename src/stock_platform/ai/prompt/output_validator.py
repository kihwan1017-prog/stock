"""STEP 11-4 — Output Schema + Policy Validation Pipeline."""

from __future__ import annotations

import json
from typing import Any

from stock_platform.ai.prompt.core_safety import (
    scan_core_safety,
    scan_forbidden_fields,
)
from stock_platform.ai.prompt.injection import detect_pii, detect_secrets
from stock_platform.ai.prompt.response_parser import (
    AIResponseParseError,
    parse_ai_response,
)
from stock_platform.ai.prompt.task_types import FORBIDDEN_OUTPUT_FIELDS


class AIOutputValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _type_ok(value: Any, expected: str | list[str] | None) -> bool:
    if expected is None:
        return True
    types = expected if isinstance(expected, list) else [expected]
    mapping = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    for t in types:
        py = mapping.get(t)
        if py and isinstance(value, py):
            if t == "number" and isinstance(value, bool):
                continue
            if t == "integer" and isinstance(value, bool):
                continue
            return True
    return False


def validate_against_json_schema(
    data: dict[str, Any],
    schema: dict[str, Any],
    *,
    path: str = "",
) -> list[str]:
    """경량 JSON Schema 검증 (draft-ish subset)."""

    errors: list[str] = []
    if not isinstance(schema, dict):
        return ["schema must be object"]

    expected_type = schema.get("type")
    if expected_type and not _type_ok(data if path else data, expected_type):
        # root: data is dict; for nested we pass value
        pass

    if schema.get("type") == "object" or "properties" in schema:
        if not isinstance(data, dict):
            errors.append(f"{path or '$'}: expected object")
            return errors
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        additional = schema.get("additionalProperties", True)
        for key in required:
            if key not in data:
                errors.append(f"{path}.{key}: required".lstrip("."))
        for key, value in data.items():
            if key not in props:
                if additional is False:
                    errors.append(f"{path}.{key}: additionalProperties=false".lstrip("."))
                continue
            errors.extend(
                validate_against_json_schema(
                    value, props[key], path=f"{path}.{key}".lstrip(".")
                )
            )
        return errors

    # primitive constraints when data is leaf
    value = data
    if expected_type and not _type_ok(value, expected_type):
        errors.append(f"{path or '$'}: type mismatch")
        return errors
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: enum mismatch")
    if isinstance(value, str):
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path}: maxLength")
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            errors.append(f"{path}: minLength")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: maximum")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path}: maxItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                errors.extend(
                    validate_against_json_schema(
                        item, item_schema, path=f"{path}[{idx}]"
                    )
                )
    return errors


def validate_ai_output(
    *,
    raw: str | None,
    json_schema: dict[str, Any] | None,
    expected_task_type: str | None = None,
    expected_schema_version: str | None = None,
    policy_rules: dict[str, Any] | None = None,
    enforcement_mode: str = "BLOCK",
) -> dict[str, Any]:
    """검증 파이프라인 → VALID / VALID_WITH_WARNINGS / BLOCKED / INVALID."""

    warnings: list[str] = []
    try:
        data = parse_ai_response(raw)
    except AIResponseParseError as exc:
        return {
            "status": "INVALID",
            "code": exc.code,
            "message": exc.message,
            "warnings": [],
            "data": None,
        }

    dumped = json.dumps(data, ensure_ascii=False)
    if detect_secrets(dumped):
        return {
            "status": "BLOCKED",
            "code": "AI_RESPONSE_SECRET_DETECTED",
            "message": "Secret detected in response",
            "warnings": [],
            "data": None,
        }
    pii = detect_pii(dumped)
    if pii:
        warnings.append(f"PII detected: {','.join(pii)}")

    core = scan_core_safety(dumped)
    if core:
        return {
            "status": "BLOCKED",
            "code": "AI_RESPONSE_POLICY_BLOCKED",
            "message": "Core safety violation",
            "warnings": [],
            "hits": core,
            "data": None,
        }

    forbidden = scan_forbidden_fields(data)
    if forbidden:
        return {
            "status": "BLOCKED",
            "code": "AI_RESPONSE_POLICY_BLOCKED",
            "message": f"Forbidden fields: {','.join(forbidden[:10])}",
            "warnings": [],
            "data": None,
        }

    if expected_task_type and data.get("task_type") not in (
        None,
        expected_task_type,
    ):
        return {
            "status": "INVALID",
            "code": "AI_RESPONSE_SCHEMA_MISMATCH",
            "message": "task_type mismatch",
            "warnings": warnings,
            "data": None,
        }

    if expected_schema_version and data.get("schema_version") not in (
        None,
        expected_schema_version,
    ):
        return {
            "status": "INVALID",
            "code": "AI_RESPONSE_UNSUPPORTED_VERSION",
            "message": "schema_version mismatch",
            "warnings": warnings,
            "data": None,
        }

    conf = data.get("confidence")
    if conf is not None:
        try:
            c = float(conf)
            if c < 0.0 or c > 1.0:
                return {
                    "status": "INVALID",
                    "code": "AI_RESPONSE_SCHEMA_MISMATCH",
                    "message": "confidence out of range",
                    "warnings": warnings,
                    "data": None,
                }
        except (TypeError, ValueError):
            return {
                "status": "INVALID",
                "code": "AI_RESPONSE_SCHEMA_MISMATCH",
                "message": "confidence not numeric",
                "warnings": warnings,
                "data": None,
            }

    if json_schema:
        schema_errors = validate_against_json_schema(data, json_schema)
        if schema_errors:
            return {
                "status": "INVALID",
                "code": "AI_RESPONSE_SCHEMA_MISMATCH",
                "message": "; ".join(schema_errors[:20]),
                "warnings": warnings,
                "data": None,
            }

    # DB Policy 규칙 (추가 패턴)
    if policy_rules:
        patterns = policy_rules.get("block_patterns") or []
        for pat in patterns:
            import re

            if re.search(str(pat), dumped, flags=re.IGNORECASE):
                if enforcement_mode == "BLOCK":
                    return {
                        "status": "BLOCKED",
                        "code": "AI_POLICY_BLOCKED_OUTPUT",
                        "message": "Policy blocked output",
                        "warnings": warnings,
                        "data": None,
                    }
                if enforcement_mode == "WARN":
                    warnings.append(f"policy warn: {pat}")
                # AUDIT_ONLY: warning only
                warnings.append(f"policy audit: {pat}")

    status = "VALID_WITH_WARNINGS" if warnings else "VALID"
    # Safe result — 금지 필드 제거된 정규화 사본
    safe = {
        k: v
        for k, v in data.items()
        if str(k).lower() not in FORBIDDEN_OUTPUT_FIELDS
    }
    return {
        "status": status,
        "code": "OK",
        "message": "validated",
        "warnings": warnings,
        "data": safe,
        "external_ai_called": False,
    }
