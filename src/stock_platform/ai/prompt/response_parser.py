"""STEP 11-4 — AI 응답 JSON Parser (eval/YAML 금지)."""

from __future__ import annotations

import json
import re
from typing import Any

from stock_platform.ai.prompt.task_types import (
    MAX_ARRAY_ITEMS,
    MAX_NESTING_DEPTH,
    MAX_RESPONSE_CHARS,
)

_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```",
    re.DOTALL | re.IGNORECASE,
)


class AIResponseParseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _check_depth(obj: Any, depth: int = 0) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise AIResponseParseError(
            "AI_RESPONSE_TOO_DEEP", "Nesting depth exceeded"
        )
    if isinstance(obj, dict):
        for value in obj.values():
            _check_depth(value, depth + 1)
    elif isinstance(obj, list):
        if len(obj) > MAX_ARRAY_ITEMS:
            raise AIResponseParseError(
                "AI_RESPONSE_ARRAY_TOO_LARGE", "Array too large"
            )
        for item in obj:
            _check_depth(item, depth + 1)


def _reject_nonfinite(obj: Any) -> None:
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            raise AIResponseParseError(
                "AI_RESPONSE_INVALID_JSON", "NaN/Infinity not allowed"
            )
    elif isinstance(obj, dict):
        for value in obj.values():
            _reject_nonfinite(value)
    elif isinstance(obj, list):
        for item in obj:
            _reject_nonfinite(item)


def parse_ai_response(raw: str | None) -> dict[str, Any]:
    """순수 JSON 또는 Markdown code fence JSON만 허용."""

    if raw is None or not str(raw).strip():
        raise AIResponseParseError("AI_RESPONSE_EMPTY", "Empty response")
    text = str(raw)
    if len(text) > MAX_RESPONSE_CHARS:
        raise AIResponseParseError(
            "AI_RESPONSE_TOO_LARGE", "Response exceeds size limit"
        )

    candidate = text.strip()
    fence = _FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
    elif candidate.startswith("```"):
        # fence 파싱 실패
        raise AIResponseParseError(
            "AI_RESPONSE_INVALID_JSON", "Malformed markdown fence"
        )

    try:
        # Python json은 NaN을 허용할 수 있어 사전 거부
        if any(tok in candidate for tok in ("NaN", "Infinity", "-Infinity")):
            raise AIResponseParseError(
                "AI_RESPONSE_INVALID_JSON", "NaN/Infinity not allowed"
            )
        data = json.loads(candidate)
    except AIResponseParseError:
        raise
    except json.JSONDecodeError as exc:
        raise AIResponseParseError(
            "AI_RESPONSE_INVALID_JSON", "Invalid JSON"
        ) from exc

    if not isinstance(data, dict):
        raise AIResponseParseError(
            "AI_RESPONSE_INVALID_JSON", "Root must be object"
        )
    _check_depth(data)
    _reject_nonfinite(data)
    return data
