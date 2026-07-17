from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.inquiry_client import (
    KiwoomOrderInquiryClient,
)
from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import (
    TradingOrderRepository,
)


@dataclass(frozen=True, slots=True)
class KiwoomRecoverySummary:
    inspected_pending: int
    matched_orders: int
    missing_local_orders: int


class KiwoomOrderRecoveryService:
    def __init__(
        self,
        *,
        session: Session,
        inquiry_client: KiwoomOrderInquiryClient,
    ) -> None:
        self._repository = TradingOrderRepository(
            session
        )
        self._inquiry_client = inquiry_client

    def recover_pending_orders(
        self,
        *,
        account_number: str,
        actor: str = "KIWOOM_RECOVERY",
    ) -> KiwoomRecoverySummary:
        inspected = 0
        matched = 0
        missing = 0
        next_key: str | None = None

        while True:
            page = (
                self._inquiry_client
                .get_pending_orders(
                    account_number=account_number,
                    continuation_key=next_key,
                )
            )

            for pending in page.items:
                inspected += 1
                entity = (
                    self._repository
                    .get_by_broker_order_id(
                        broker_code="KIWOOM",
                        broker_order_id=(
                            pending.broker_order_id
                        ),
                    )
                )

                if entity is None:
                    missing += 1
                    continue

                matched += 1
                entity.filled_quantity = (
                    pending.filled_quantity
                )
                entity.remaining_quantity = (
                    pending.remaining_quantity
                )

                current = OrderStatus(
                    entity.status_code
                )

                if (
                    pending.filled_quantity > 0
                    and current
                    == OrderStatus.ACCEPTED
                ):
                    self._repository.change_status(
                        entity=entity,
                        new_status=(
                            OrderStatus
                            .PARTIALLY_FILLED
                        ),
                        actor=actor,
                        reason_code=(
                            "RECOVERED_PARTIAL_FILL"
                        ),
                    )

            if not page.has_next or not page.next_key:
                break

            next_key = page.next_key

        return KiwoomRecoverySummary(
            inspected_pending=inspected,
            matched_orders=matched,
            missing_local_orders=missing,
        )
