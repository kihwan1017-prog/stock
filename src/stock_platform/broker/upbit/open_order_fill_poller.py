"""Upbit ACCEPTED/PARTIALLY_FILLED → broker terminal fill sync poller.

Outbox는 접수 직후 1회 fill-sync만 수행한다. LIMIT SELL 등 지연 체결은
이 poller가 local open 주문을 주기적으로 조회해 UpbitFillSyncService에 위임한다.
실주문 재제출 없음 — GET order 조회만.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus

logger = structlog.get_logger(__name__)

_OPEN_STATUSES = (
    OrderStatus.PENDING.value,
    OrderStatus.SUBMITTING.value,
    OrderStatus.SENT.value,
    OrderStatus.ACCEPTED.value,
    OrderStatus.PARTIALLY_FILLED.value,
)


class UpbitOpenOrderFillPoller:
    """로컬 open Upbit 주문 → UpbitFillSyncService.sync_by_order_id."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def select_due_order_ids(self, *, limit: int = 40) -> list[int]:
        stmt = (
            select(TradingOrderEntity.order_id)
            .where(
                TradingOrderEntity.broker_code == "UPBIT",
                TradingOrderEntity.status_code.in_(_OPEN_STATUSES),
                TradingOrderEntity.broker_order_id.is_not(None),
            )
            .order_by(TradingOrderEntity.updated_at.asc())
            .limit(max(1, int(limit)))
        )
        return [int(x) for x in self._session.scalars(stmt).all()]

    def poll_once(
        self,
        *,
        limit: int = 40,
        actor: str = "UPBIT_OPEN_ORDER_FILL_POLLER",
    ) -> dict[str, Any]:
        from stock_platform.broker.upbit.fill_sync_service import (
            UpbitFillSyncService,
        )

        ids = self.select_due_order_ids(limit=limit)
        fill_sync = UpbitFillSyncService(self._session)
        checked = 0
        updated = 0
        errors: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []

        for order_id in ids:
            checked += 1
            before = self._session.get(TradingOrderEntity, int(order_id))
            before_status = (
                str(before.status_code) if before is not None else None
            )
            try:
                result = fill_sync.sync_by_order_id(
                    int(order_id), actor=actor
                )
                after_status = result.order_status
                if (
                    after_status != before_status
                    or result.new_executions > 0
                ):
                    updated += 1
                results.append(
                    {
                        "order_id": result.order_id,
                        "status": after_status,
                        "new_executions": result.new_executions,
                        "already_processed": result.already_processed,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "order_id": int(order_id),
                        "error_type": exc.__class__.__name__,
                        "message": str(exc)[:200],
                    }
                )
                logger.warning(
                    "upbit_open_order_fill_poll_failed",
                    order_id=int(order_id),
                    error_type=exc.__class__.__name__,
                )

        return {
            "checked": checked,
            "updated": updated,
            "errors": len(errors),
            "error_detail": errors[:10],
            "results": results,
        }
