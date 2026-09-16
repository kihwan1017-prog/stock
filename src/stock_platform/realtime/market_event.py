"""STEP 8-5-9 — 정규화 Realtime Market Event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RealtimeMarketEvent:
    """Broker 원시 시세를 Scope Consumer에 전달하는 정규화 Event."""

    broker_code: str
    market_type: str
    symbol: str
    event_type: str
    event_time: datetime
    received_at: datetime
    # 시세 거래소(PAPER/KRX/UPBIT). broker_code(데이터 소스)와 분리
    exchange_code: str | None = None
    price: Decimal | None = None
    volume: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    raw_sequence: int | None = None
    change_rate: Decimal | None = None
    source_code: str | None = None

    @property
    def subscription_key(self) -> str:
        return (
            f"{self.broker_code.upper()}|"
            f"{self.market_type.upper()}|"
            f"{self.symbol.upper()}"
        )
