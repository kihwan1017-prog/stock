from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from stock_platform.order.models import OrderStatus

class InvalidOrderStateTransition(ValueError):
    def __init__(self, *, current: OrderStatus, target: OrderStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Invalid order state transition: {current.value} -> {target.value}")

@dataclass(frozen=True, slots=True)
class OrderStateTransitionCommand:
    order_id: int
    target_status: OrderStatus
    actor: str
    reason_code: str | None = None
    message: str | None = None
    detail_payload: dict[str, Any] | None = None

@dataclass(frozen=True, slots=True)
class OrderStateTransitionResult:
    order_id: int
    previous_status: OrderStatus
    current_status: OrderStatus
    changed_at: datetime
