from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
    BrokerSnapshotBindingError,
)
from stock_platform.broker.kiwoom.account_client import (
    KiwoomAccountClient,
)
from stock_platform.broker.kiwoom.account_mapper import (
    KiwoomAccountMapper,
)
from stock_platform.trading.account_models import UserBrokerAccount


class KiwoomAccountSyncService:
    def __init__(
        self,
        *,
        session: Session,
        account_client: KiwoomAccountClient,
        user_broker_account_id: int | None = None,
    ) -> None:
        self._session = session
        self._client = account_client
        self._uba_id = (
            int(user_broker_account_id)
            if user_broker_account_id is not None
            else None
        )
        self._repository = BrokerAccountSnapshotRepository(session)

    def _resolve_uba_id(self, account_number: str) -> int:
        # STEP 8-5-18 — UBA 필수 (해시 휴리스틱 폴백 제거)
        if self._uba_id is None:
            raise BrokerSnapshotBindingError(
                "KIWOOM sync requires user_broker_account_id"
            )
        uba = self._session.get(UserBrokerAccount, self._uba_id)
        if uba is None:
            raise BrokerSnapshotBindingError(
                f"UBA not found: {self._uba_id}"
            )
        if str(uba.broker_code).upper() != "KIWOOM":
            raise BrokerSnapshotBindingError(
                "UBA broker_code must be KIWOOM"
            )
        return int(self._uba_id)

    async def synchronize(
        self, *, user_broker_account_id: int | None = None
    ):
        if user_broker_account_id is not None:
            self._uba_id = int(user_broker_account_id)
        account_number = await self._client.get_account_number()
        uba_id = self._resolve_uba_id(account_number)
        deposit = await self._client.get_deposit_detail()
        balance = await self._client.get_account_balance()

        result = KiwoomAccountMapper.map(
            account_number=account_number,
            deposit_payload=deposit,
            balance_payload=balance,
        )
        entity = self._repository.save(
            result, user_broker_account_id=uba_id
        )

        return {
            "broker_account_snapshot_id": (
                entity.broker_account_snapshot_id
            ),
            "user_broker_account_id": uba_id,
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
            "snapshot_generation": int(entity.snapshot_generation),
            "snapshot_hash": entity.snapshot_hash,
            "snapshot_status": entity.snapshot_status,
        }
