from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.ws_models import (
    KiwoomOrderEventType,
    KiwoomOrderExecutionEvent,
)
from stock_platform.broker.pending_entities import (
    BrokerPendingOrderEntity,
)


class KiwoomOrderExecutionEventService:
    """체결 이벤트를 미체결 스냅샷에 즉시 반영한다."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def apply(
        self,
        event: KiwoomOrderExecutionEvent,
    ) -> dict:
        entity = self._session.scalar(
            select(BrokerPendingOrderEntity).where(
                BrokerPendingOrderEntity.broker_code
                == "KIWOOM",
                BrokerPendingOrderEntity.account_number
                == event.account_number,
                BrokerPendingOrderEntity.broker_order_id
                == event.broker_order_id,
            )
        )

        if entity is None:
            entity = BrokerPendingOrderEntity(
                broker_code="KIWOOM",
                account_number=event.account_number,
                broker_order_id=event.broker_order_id,
                exchange_code=event.exchange_code,
                symbol=event.symbol,
                name="",
                side=event.side,
                order_type="UNKNOWN",
                order_quantity=event.order_quantity,
                order_price=None,
                filled_quantity=event.filled_quantity,
                remaining_quantity=(
                    event.remaining_quantity
                ),
                average_fill_price=(
                    event.average_fill_price
                    or event.fill_price
                ),
                status_code=event.event_type.value,
                ordered_at=event.event_time,
                raw_data=event.raw_data,
                synchronized_at=event.received_at,
            )
            self._session.add(entity)
        else:
            entity.filled_quantity = event.filled_quantity
            entity.remaining_quantity = (
                event.remaining_quantity
            )
            entity.average_fill_price = (
                event.average_fill_price
                or event.fill_price
            )
            entity.status_code = event.event_type.value
            entity.raw_data = event.raw_data
            entity.synchronized_at = event.received_at

        self._session.commit()

        terminal = event.event_type in {
            KiwoomOrderEventType.FILLED,
            KiwoomOrderEventType.CANCELLED,
            KiwoomOrderEventType.REJECTED,
        }

        return {
            "broker_order_id": event.broker_order_id,
            "status_code": event.event_type.value,
            "terminal": terminal,
            "filled_quantity": str(
                event.filled_quantity
            ),
            "remaining_quantity": str(
                event.remaining_quantity
            ),
        }
