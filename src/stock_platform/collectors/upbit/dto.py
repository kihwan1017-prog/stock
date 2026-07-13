from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class UpbitDailyPriceDTO:
    trade_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    trade_value: Decimal
    change_rate: Decimal | None = None

    def to_price_row(self) -> dict[str, Any]:
        return asdict(self)
