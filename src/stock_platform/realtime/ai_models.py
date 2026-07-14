from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class RealtimeAiAction(StrEnum):
    KEEP = "KEEP"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    WATCH = "WATCH"


@dataclass(frozen=True, slots=True)
class RealtimeAiReviewRequest:
    exchange_code: str
    symbol: str
    current_price: Decimal
    current_quantity: Decimal
    average_entry_price: Decimal | None
    news_limit: int = 10
    disclosure_limit: int = 10
    lookback_days: int = 30


@dataclass(frozen=True, slots=True)
class RealtimeAiReviewResult:
    exchange_code: str
    symbol: str
    action: RealtimeAiAction
    score: Decimal
    confidence: Decimal
    summary: str
    risk_factors: list[str]
    reviewed_at: datetime
