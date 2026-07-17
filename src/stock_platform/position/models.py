from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

@dataclass(slots=True)
class Position:
    account_id: str
    market: str
    symbol: str
    quantity: Decimal = Decimal("0")
    average_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    last_price: Decimal | None = None

    @property
    def market_value(self) -> Decimal:
        return self.quantity * (self.last_price or self.average_price)

    @property
    def unrealized_pnl(self) -> Decimal:
        if self.last_price is None:
            return Decimal("0")
        return (self.last_price - self.average_price) * self.quantity
