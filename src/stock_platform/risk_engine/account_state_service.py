from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.broker.account_models import (
    BrokerAccountSnapshotEntity,
)
from stock_platform.risk_engine.models import (
    RiskAccountState,
)
from stock_platform.trading.account_identity import (
    AccountIdentityError,
    AccountIdentityErrorCode,
)


ZERO = Decimal("0")


class RiskAccountStateService:
    """브로커/Paper 계좌 상태를 Risk Engine 입력으로 변환한다."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def load_by_uba(
        self,
        *,
        user_broker_account_id: int,
        exchange_code: str,
        symbol: str,
    ) -> RiskAccountState:
        """ACTIVE Snapshot by UBA."""

        from stock_platform.broker.account_repository import (
            BrokerAccountSnapshotRepository,
        )

        account, positions = BrokerAccountSnapshotRepository(
            self._session
        ).get_active_by_uba(int(user_broker_account_id))
        if account is None:
            raise LookupError(
                "Broker account snapshot not found for UBA"
            )
        return self._to_state(
            account=account,
            positions=positions,
            exchange_code=exchange_code,
            symbol=symbol,
        )

    def load_by_paper_account(
        self,
        *,
        paper_account_id: int,
        exchange_code: str,
        symbol: str,
    ) -> RiskAccountState:
        """PaperAccount + PaperPosition 기준 상태."""

        from sqlalchemy import select

        from stock_platform.trading.account_models import (
            PaperAccount,
            PaperPosition,
        )

        paper = self._session.get(PaperAccount, int(paper_account_id))
        if paper is None:
            raise LookupError(
                f"Paper account not found: {paper_account_id}"
            )
        positions = list(
            self._session.scalars(
                select(PaperPosition).where(
                    PaperPosition.account_id == int(paper_account_id),
                    PaperPosition.quantity > 0,
                )
            )
        )
        symbol_position = next(
            (
                item
                for item in positions
                if str(getattr(item, "exchange_code", "")).upper()
                == exchange_code.upper()
                and str(item.symbol).upper() == symbol.upper()
            ),
            None,
        )
        invested = sum(
            (
                Decimal(item.quantity)
                * Decimal(item.average_entry_price)
                for item in positions
            ),
            ZERO,
        )
        cash = Decimal(paper.available_cash)
        return RiskAccountState(
            cash_balance=cash,
            total_asset_value=cash + invested,
            invested_amount=invested,
            daily_realized_profit_loss=Decimal(
                paper.realized_profit_loss or ZERO
            ),
            daily_unrealized_profit_loss=ZERO,
            open_position_count=len(positions),
            symbol_position_quantity=(
                Decimal(symbol_position.quantity)
                if symbol_position is not None
                else ZERO
            ),
        )

    def load(self, **kwargs):  # noqa: ANN003
        """제거됨 — load_by_uba / load_by_paper_account 사용."""

        raise AccountIdentityError(
            AccountIdentityErrorCode.LEGACY_ACCOUNT_NUMBER_ONLY,
            "RiskAccountStateService.load(account_number=...) removed; "
            "use load_by_uba or load_by_paper_account",
        )

    def _to_state(
        self,
        *,
        account: BrokerAccountSnapshotEntity,
        positions: list,
        exchange_code: str,
        symbol: str,
    ) -> RiskAccountState:
        positions = [
            item
            for item in positions
            if Decimal(item.quantity) > 0
        ]
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
