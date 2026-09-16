"""Kiwoom ACCEPTED/PARTIALLY_FILLED → ka10076 fill reconcile poller.

Upbit open_order_fill_poller와 대칭. 실주문 재제출 없음 — 조회 TR만.
pending(ka10075)에서 빠진 전량체결을 execution history로 terminal sync.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.credential_adapter_factory import (
    build_kiwoom_account_client_for_uba,
    build_kiwoom_order_inquiry_client_for_uba,
)
from stock_platform.broker.kiwoom.recovery import (
    KiwoomOrderRecoveryService,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus

logger = structlog.get_logger(__name__)

_OPEN_STATUSES = (
    OrderStatus.PENDING.value,
    OrderStatus.SENT.value,
    OrderStatus.ACCEPTED.value,
    OrderStatus.PARTIALLY_FILLED.value,
)


class KiwoomOpenOrderFillPoller:
    """로컬 open Kiwoom 주문 → ka10076 → ExecutionSync."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def select_due_uba_ids(self, *, limit: int = 20) -> list[int]:
        stmt = (
            select(TradingOrderEntity.user_broker_account_id)
            .where(
                TradingOrderEntity.broker_code == "KIWOOM",
                TradingOrderEntity.status_code.in_(_OPEN_STATUSES),
                TradingOrderEntity.broker_order_id.is_not(None),
                TradingOrderEntity.user_broker_account_id.is_not(None),
            )
            .distinct()
            .limit(max(1, int(limit)))
        )
        return [int(x) for x in self._session.scalars(stmt).all() if x]

    def poll_once(
        self,
        *,
        limit: int = 20,
        actor: str = "KIWOOM_OPEN_ORDER_FILL_POLLER",
    ) -> dict[str, Any]:
        uba_ids = self.select_due_uba_ids(limit=limit)
        checked = 0
        updated = 0
        errors: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []

        for uba_id in uba_ids:
            checked += 1
            try:
                _client, account_number = build_kiwoom_account_client_for_uba(
                    self._session,
                    int(uba_id),
                )
                inquiry = build_kiwoom_order_inquiry_client_for_uba(
                    self._session,
                    int(uba_id),
                )
                summary = KiwoomOrderRecoveryService(
                    session=self._session,
                    inquiry_client=inquiry,
                ).recover_open_orders_from_executions(
                    account_number=str(account_number),
                    user_broker_account_id=int(uba_id),
                    actor=actor,
                )
                if (
                    summary.reconciled_from_executions > 0
                    or summary.new_executions > 0
                ):
                    updated += 1
                results.append(
                    {
                        "uba_id": int(uba_id),
                        "matched": summary.matched_orders,
                        "reconciled": summary.reconciled_from_executions,
                        "new_executions": summary.new_executions,
                        "inspected_executions": summary.inspected_executions,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "uba_id": int(uba_id),
                        "error_type": exc.__class__.__name__,
                        "message": str(exc)[:200],
                    }
                )
                logger.warning(
                    "kiwoom_open_order_fill_poll_failed",
                    uba_id=int(uba_id),
                    error_type=exc.__class__.__name__,
                )
                try:
                    self._session.rollback()
                except Exception:  # noqa: BLE001
                    pass

        return {
            "checked": checked,
            "updated": updated,
            "errors": len(errors),
            "error_detail": errors[:10],
            "results": results,
        }

