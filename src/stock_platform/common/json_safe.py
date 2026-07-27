"""JSON/JSONB 안전 직렬화 — 금액 정밀도 보존 (Decimal → str)."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


def to_jsonable(value: Any) -> Any:
    """JSONB·json.dumps 가능 형태로 재귀 변환.

    Decimal은 정밀도 유지를 위해 str로 보존한다 (float 금지).
    변환 불가 타입은 TypeError를 올려 fail-closed 한다.
    """

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        # 과학적 표기 금지 — fixed-point 문자열로 정밀도 보존
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, bytes):
        raise TypeError(
            f"Object of type {type(value).__name__} is not JSON serializable"
        )
    # Pydantic / dataclass dump 결과가 아닌 임의 객체는 거부
    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )


def dumps_jsonable(value: Any, *, ensure_ascii: bool = False) -> str:
    """직렬화 검증용 — to_jsonable 후 json.dumps (기본 변환기 없음)."""

    return json.dumps(
        to_jsonable(value),
        ensure_ascii=ensure_ascii,
        separators=(",", ":"),
        sort_keys=True,
    )
