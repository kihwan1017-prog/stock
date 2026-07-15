from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from stock_platform.broker.pending_entities import BrokerPendingOrderEntity

class BrokerPendingOrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_for_account(self, broker_code: str, account_number: str, rows) -> int:
        self._session.execute(
            delete(BrokerPendingOrderEntity).where(
                BrokerPendingOrderEntity.broker_code == broker_code,
                BrokerPendingOrderEntity.account_number == account_number,
            )
        )
        for item in rows:
            self._session.add(BrokerPendingOrderEntity(
                broker_code=item.broker_code, account_number=item.account_number,
                broker_order_id=item.broker_order_id, exchange_code=item.exchange_code,
                symbol=item.symbol, name=item.name, side=item.side,
                order_type=item.order_type, order_quantity=item.order_quantity,
                order_price=item.order_price, filled_quantity=item.filled_quantity,
                remaining_quantity=item.remaining_quantity,
                average_fill_price=item.average_fill_price,
                status_code=item.status.value, ordered_at=item.ordered_at,
                raw_data=item.raw_data, synchronized_at=item.synchronized_at,
            ))
        self._session.commit()
        return len(rows)

    def list_for_account(self, broker_code: str, account_number: str):
        return list(self._session.scalars(
            select(BrokerPendingOrderEntity).where(
                BrokerPendingOrderEntity.broker_code == broker_code,
                BrokerPendingOrderEntity.account_number == account_number,
            ).order_by(BrokerPendingOrderEntity.broker_pending_order_id.desc())
        ))
