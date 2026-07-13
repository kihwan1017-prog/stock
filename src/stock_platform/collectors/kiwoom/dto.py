from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class DailyPriceDTO:
    """키움 일봉 응답을 내부 표준 형식으로 변환한 객체."""

    trade_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    trade_value: Decimal
    change_rate: Decimal | None = None

    def to_price_row(self) -> dict[str, Any]:
        """PriceDailyService.save_many()에 전달할 dict로 변환한다."""
        return asdict(self)
