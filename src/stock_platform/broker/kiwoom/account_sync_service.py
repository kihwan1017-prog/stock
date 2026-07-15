from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
)
from stock_platform.broker.kiwoom.account_client import (
    KiwoomAccountClient,
)
from stock_platform.broker.kiwoom.account_mapper import (
    KiwoomAccountMapper,
)


class KiwoomAccountSyncService:
    def __init__(
        self,
        *,
        session: Session,
        account_client: KiwoomAccountClient,
    ) -> None:
        self._client = account_client
        self._repository = (
            BrokerAccountSnapshotRepository(session)
        )

    async def synchronize(self):
        account_number = (
            await self._client.get_account_number()
        )
        deposit = await self._client.get_deposit_detail()
        balance = await self._client.get_account_balance()

        result = KiwoomAccountMapper.map(
            account_number=account_number,
            deposit_payload=deposit,
            balance_payload=balance,
        )
        entity = self._repository.save(result)

        return {
            "broker_account_snapshot_id": (
                entity.broker_account_snapshot_id
            ),
            "broker_code": result.broker_code,
            "account_number": result.account_number,
            "deposit_amount": result.deposit_amount,
            "available_order_amount": (
                result.available_order_amount
            ),
            "total_evaluation_amount": (
                result.total_evaluation_amount
            ),
            "total_profit_loss": (
                result.total_profit_loss
            ),
            "position_count": len(result.positions),
            "synchronized_at": result.synchronized_at,
        }
