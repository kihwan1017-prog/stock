from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import TradingOrderRepository


@dataclass(frozen=True, slots=True)
class OrderTimeoutSummary:
    inspected: int
    timed_out: int


class OrderTimeoutService:
    """장시간 미확정 주문을 FAILED(ORDER_TIMEOUT)로 정리한다."""

    def __init__(self, session: Session) -> None:
        self._repository = TradingOrderRepository(session)
        self._session = session

    def fail_stale_orders(
        self,
        *,
        timeout_seconds: int = 300,
        limit: int = 100,
        actor: str = "ORDER_TIMEOUT",
    ) -> OrderTimeoutSummary:
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=max(30, timeout_seconds)
        )
        rows = self._repository.list_stale_open_orders(
            older_than=cutoff,
            statuses=[
                OrderStatus.PENDING.value,
                OrderStatus.SENT.value,
            ],
            limit=limit,
        )
        timed_out = 0
        for entity in rows:
            current = OrderStatus(entity.status_code)
            # SENT만 바로 FAILED, PENDING도 FAILED 허용
            if current in {
                OrderStatus.PENDING,
                OrderStatus.SENT,
            }:
                self._repository.change_status(
                    entity=entity,
                    new_status=OrderStatus.FAILED,
                    actor=actor,
                    reason_code="ORDER_TIMEOUT",
                    message=(
                        f"No broker confirmation within "
                        f"{timeout_seconds}s"
                    ),
                    commit=False,
                )
                timed_out += 1
        if timed_out:
            self._session.commit()
        return OrderTimeoutSummary(
            inspected=len(rows),
            timed_out=timed_out,
        )
