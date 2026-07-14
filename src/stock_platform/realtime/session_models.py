from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TradingSessionPhase(StrEnum):
    PRE_MARKET = "PRE_MARKET"
    MARKET_OPEN = "MARKET_OPEN"
    MARKET_CLOSE = "MARKET_CLOSE"
    AFTER_MARKET = "AFTER_MARKET"


@dataclass(frozen=True, slots=True)
class TradingSessionResult:
    phase: TradingSessionPhase
    executed: bool
    message: str
    executed_at: datetime
