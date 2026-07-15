from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class StrategySelectionStatus(StrEnum):
    SELECTED = "SELECTED"
    FALLBACK = "FALLBACK"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class StrategySelectionCandidate:
    rank: int
    strategy_code: str
    strategy_performance_run_id: int
    market_code: str
    symbol: str | None
    run_type: str
    score: Decimal
    total_return_rate: Decimal
    maximum_drawdown_rate: Decimal
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    win_rate: Decimal
    profit_factor: Decimal | None
    total_trade_count: int


@dataclass(frozen=True, slots=True)
class StrategySelectionDecision:
    status: StrategySelectionStatus
    selected_strategy_code: str
    selected_performance_run_id: int
    confidence_score: Decimal
    reason: str
    risk_notes: list[str]
    alternatives: list[str]
    model_name: str
    selected_at: datetime
    raw_response: dict[str, Any]
