from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.broker.account_models import (
    BrokerAccountSnapshotEntity,
    BrokerPositionSnapshotEntity,
)
from stock_platform.risk_engine.models import (
    RiskAccountState,
)


ZERO = Decimal("0")


class RiskAccountStateService:
    """브로커 계좌 스냅샷을 Risk Engine 입력 상태로 변환한다."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def load(
        self,
        *,
        broker_code: str,
        account_number: str,
        exchange_code: str,
        symbol: str,
    ) -> RiskAccountState:
        account = self._session.scalar(
            select(BrokerAccountSnapshotEntity).where(
                BrokerAccountSnapshotEntity.broker_code
                == broker_code.upper(),
                BrokerAccountSnapshotEntity.account_number
                == account_number,
            )
        )

        if account is None:
            raise LookupError(
                "Broker account snapshot not found"
            )

        positions = list(
            self._session.scalars(
                select(BrokerPositionSnapshotEntity).where(
                    BrokerPositionSnapshotEntity.broker_code
                    == broker_code.upper(),
                    BrokerPositionSnapshotEntity.account_number
                    == account_number,
                    BrokerPositionSnapshotEntity.quantity > 0,
                )
            )
        )

        symbol_position = next(
            (
                item
                for item in positions
                if item.exchange_code.upper()
                == exchange_code.upper()
                and item.symbol.upper() == symbol.upper()
            ),
            None,
        )

        invested_amount = sum(
            (
                Decimal(item.evaluation_amount)
                for item in positions
            ),
            ZERO,
        )

        unrealized_profit_loss = sum(
            (
                Decimal(item.profit_loss)
                for item in positions
            ),
            ZERO,
        )

        total_asset_value = (
            Decimal(account.deposit_amount)
            + invested_amount
        )

        return RiskAccountState(
            cash_balance=Decimal(
                account.available_order_amount
            ),
            total_asset_value=total_asset_value,
            invested_amount=invested_amount,
            daily_realized_profit_loss=Decimal(
                account.total_profit_loss
            ),
            daily_unrealized_profit_loss=(
                unrealized_profit_loss
            ),
            open_position_count=len(positions),
            symbol_position_quantity=(
                Decimal(symbol_position.quantity)
                if symbol_position is not None
                else ZERO
            ),
        )
