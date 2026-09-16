from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from stock_platform.broker.pending_entities import BrokerPendingOrderEntity
from stock_platform.trading.account_identity import (
    AccountIdentityError,
    AccountIdentityErrorCode,
)
from stock_platform.trading.account_masking import mask_account_number


class BrokerPendingOrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_for_uba(
        self,
        *,
        broker_code: str,
        user_broker_account_id: int,
        rows,
        broker_account_number: str | None = None,
    ) -> int:
        """UBA 단위 미체결 교체 — 내부 식별 기준."""

        uba_id = int(user_broker_account_id)
        if uba_id <= 0:
            raise AccountIdentityError(
                AccountIdentityErrorCode.UBA_REQUIRED,
                "user_broker_account_id required for pending replace",
            )
        storage_token = f"UBA:{uba_id}"
        masked = mask_account_number(broker_account_number) if broker_account_number else storage_token

        self._session.execute(
            delete(BrokerPendingOrderEntity).where(
                BrokerPendingOrderEntity.broker_code == broker_code.upper(),
                BrokerPendingOrderEntity.user_broker_account_id == uba_id,
            )
        )
        for item in rows:
            self._session.add(
                BrokerPendingOrderEntity(
                    broker_code=item.broker_code,
                    account_number=storage_token,
                    user_broker_account_id=uba_id,
                    masked_account_ref=masked,
                    broker_order_id=item.broker_order_id,
                    exchange_code=item.exchange_code,
                    symbol=item.symbol,
                    name=item.name,
                    side=item.side,
                    order_type=item.order_type,
                    order_quantity=item.order_quantity,
                    order_price=item.order_price,
                    filled_quantity=item.filled_quantity,
                    remaining_quantity=item.remaining_quantity,
                    average_fill_price=item.average_fill_price,
                    status_code=item.status.value
                    if hasattr(item.status, "value")
                    else str(item.status),
                    ordered_at=item.ordered_at,
                    raw_data=item.raw_data,
                    synchronized_at=item.synchronized_at,
                )
            )
        self._session.commit()
        return len(rows)

    def list_for_uba(self, broker_code: str, user_broker_account_id: int):
        return list(
            self._session.scalars(
                select(BrokerPendingOrderEntity)
                .where(
                    BrokerPendingOrderEntity.broker_code == broker_code.upper(),
                    BrokerPendingOrderEntity.user_broker_account_id
                    == int(user_broker_account_id),
                )
                .order_by(BrokerPendingOrderEntity.broker_pending_order_id.desc())
            )
        )

    def replace_for_account(self, broker_code: str, account_number: str, rows) -> int:
        """제거됨 — UBA 경로만 허용."""

        raise AccountIdentityError(
            AccountIdentityErrorCode.LEGACY_ACCOUNT_NUMBER_ONLY,
            "replace_for_account removed; use replace_for_uba",
        )

    def list_for_account(self, broker_code: str, account_number: str):
        raise AccountIdentityError(
            AccountIdentityErrorCode.LEGACY_ACCOUNT_NUMBER_ONLY,
            "list_for_account removed; use list_for_uba",
        )
