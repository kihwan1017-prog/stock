# -*- coding: utf-8 -*-
"""Data-quality status helpers — NULL vs 0 must stay distinct."""

from __future__ import annotations

from typing import Any

from stock_platform.operation.upbit_strategy_observability.constants import (
    CANONICAL_TZ,
    DISPLAY_TZ,
    DQ_AVAILABLE,
    DQ_NOT_APPLICABLE,
    DQ_NOT_COLLECTED_RATE_LIMIT_SAFETY,
    DQ_OBSERVABILITY_WRITE_FAILED,
    DQ_PENDING_FUTURE_DATA,
    DQ_SOURCE_DATA_MISSING,
)

ALL_DQ_STATES = frozenset(
    {
        DQ_AVAILABLE,
        DQ_PENDING_FUTURE_DATA,
        DQ_SOURCE_DATA_MISSING,
        DQ_NOT_COLLECTED_RATE_LIMIT_SAFETY,
        DQ_NOT_APPLICABLE,
        DQ_OBSERVABILITY_WRITE_FAILED,
    }
)


def field_status(
    *,
    value: Any,
    status: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Wrap a field so consumers never confuse NULL with literal 0."""

    if status not in ALL_DQ_STATES:
        status = DQ_SOURCE_DATA_MISSING
    return {
        "value": value,  # may be None; never coerced to 0
        "status": status,
        "reason": reason,
        "canonical_tz": CANONICAL_TZ,
        "display_tz": DISPLAY_TZ,
    }


def null_with_reason(status: str, reason: str) -> dict[str, Any]:
    return field_status(value=None, status=status, reason=reason)
