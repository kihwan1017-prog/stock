from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class KiwoomExecutionEvent:
    broker_order_id: str
    broker_execution_id: str
    symbol: str
    side_code: str | None
    execution_price: Decimal
    execution_quantity: Decimal
    remaining_quantity: Decimal | None
    executed_at: datetime
    raw_payload: dict[str, Any]
