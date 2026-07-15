from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class WalkForwardWindowPerformanceInput:
    window_no: int
    train_start_date: date
    train_end_date: date
    test_start_date: date
    test_end_date: date
    parameter_payload: dict[str, Any]
    result_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WalkForwardPerformanceInput:
    strategy_code: str
    market_code: str
    symbol: str | None
    period_start_date: date
    period_end_date: date
    windows: list[WalkForwardWindowPerformanceInput]
    aggregate_parameter_payload: dict[str, Any]
