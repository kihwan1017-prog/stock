from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from stock_platform.broker.account_dto import (
    BrokerAccountSyncResult,
)
from stock_platform.broker.account_models import (
    BrokerAccountSnapshotEntity,
    BrokerPositionSnapshotEntity,
)


class BrokerAccountSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(
        self,
        result: BrokerAccountSyncResult,
    ) -> BrokerAccountSnapshotEntity:
        account = self._session.scalar(
            select(BrokerAccountSnapshotEntity).where(
                BrokerAccountSnapshotEntity.broker_code
                == result.broker_code,
                BrokerAccountSnapshotEntity.account_number
                == result.account_number,
            )
        )

        if account is None:
            account = BrokerAccountSnapshotEntity(
                broker_code=result.broker_code,
                account_number=result.account_number,
            )
            self._session.add(account)

        account.deposit_amount = result.deposit_amount
        account.available_order_amount = (
            result.available_order_amount
        )
        account.total_purchase_amount = (
            result.total_purchase_amount
        )
        account.total_evaluation_amount = (
            result.total_evaluation_amount
        )
        account.total_profit_loss = result.total_profit_loss
        account.total_return_rate = result.total_return_rate
        account.raw_data = result.raw_data
        account.synchronized_at = result.synchronized_at

        self._session.execute(
            delete(BrokerPositionSnapshotEntity).where(
                BrokerPositionSnapshotEntity.broker_code
                == result.broker_code,
                BrokerPositionSnapshotEntity.account_number
                == result.account_number,
            )
        )

        for item in result.positions:
            self._session.add(
                BrokerPositionSnapshotEntity(
                    broker_code=result.broker_code,
                    account_number=result.account_number,
                    exchange_code=item.exchange_code,
                    symbol=item.symbol,
                    name=item.name,
                    quantity=item.quantity,
                    available_quantity=(
                        item.available_quantity
                    ),
                    average_purchase_price=(
                        item.average_purchase_price
                    ),
                    current_price=item.current_price,
                    purchase_amount=item.purchase_amount,
                    evaluation_amount=(
                        item.evaluation_amount
                    ),
                    profit_loss=item.profit_loss,
                    return_rate=item.return_rate,
                    raw_data=item.raw_data,
                    synchronized_at=(
                        result.synchronized_at
                    ),
                )
            )

        self._session.commit()
        self._session.refresh(account)
        return account

    def get_latest(
        self,
        *,
        broker_code: str,
        account_number: str,
    ):
        account = self._session.scalar(
            select(BrokerAccountSnapshotEntity).where(
                BrokerAccountSnapshotEntity.broker_code
                == broker_code.upper(),
                BrokerAccountSnapshotEntity.account_number
                == account_number,
            )
        )
        positions = list(
            self._session.scalars(
                select(BrokerPositionSnapshotEntity)
                .where(
                    BrokerPositionSnapshotEntity.broker_code
                    == broker_code.upper(),
                    BrokerPositionSnapshotEntity.account_number
                    == account_number,
                )
                .order_by(
                    BrokerPositionSnapshotEntity.symbol
                )
            )
        )
        return account, positions
