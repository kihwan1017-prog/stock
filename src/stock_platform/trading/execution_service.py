from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.trading.account_repository import (
    PaperAccountRepository,
)
from stock_platform.trading.account_service import (
    PaperAccountService,
)
from stock_platform.trading.models import (
    OrderSide,
    PaperOrder,
)
from stock_platform.trading.paper_engine import (
    PaperOrderValidationError,
)
from stock_platform.trading.repository import (
    PaperOrderRepository,
)
from stock_platform.trading.service import (
    PaperOrderService,
)


@dataclass(frozen=True, slots=True)
class OrderFillApplicationResult:
    order_id: int
    account_id: int
    trade_id: int
    order_status: str
    order_filled_quantity: Decimal
    order_average_fill_price: Decimal | None
    account_available_cash: Decimal
    account_realized_profit_loss: Decimal
    symbol: str
    side: str
    fill_quantity: Decimal
    fill_price: Decimal
    trade_amount: Decimal
    trade_realized_profit_loss: Decimal


class PaperExecutionService:
    """
    모의 주문 체결과 모의 계좌 반영을 하나의 트랜잭션 흐름으로
    연결한다.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._order_repository = PaperOrderRepository(session)
        self._account_repository = PaperAccountRepository(session)
        self._order_service = PaperOrderService(
            self._order_repository
        )
        self._account_service = PaperAccountService(
            self._account_repository
        )

    def apply_fill(
        self,
        *,
        account_id: int,
        order_id: int,
        fill_quantity: Decimal,
        fill_price: Decimal,
    ) -> OrderFillApplicationResult:
        if fill_quantity <= 0:
            raise ValueError(
                "fill_quantity must be greater than zero"
            )
        if fill_price <= 0:
            raise ValueError(
                "fill_price must be greater than zero"
            )

        order = self._order_repository.get(order_id)
        if order is None:
            raise LookupError(
                f"Paper order not found: {order_id}"
            )

        account = self._account_repository.get_account(
            account_id
        )
        if account is None:
            raise LookupError(
                f"Paper account not found: {account_id}"
            )

        side = OrderSide(order.side)

        try:
            self._order_service.fill(
                order_id=order_id,
                fill_quantity=fill_quantity,
                fill_price=fill_price,
            )

            trade = self._account_service.apply_fill(
                account_id=account_id,
                exchange_code=order.exchange_code,
                symbol=order.symbol,
                side=side,
                quantity=fill_quantity,
                fill_price=fill_price,
                order_id=order.order_id,
            )
        except Exception:
            self._session.rollback()
            raise

        refreshed_order = self._order_repository.get(order_id)
        refreshed_account = (
            self._account_repository.get_account(
                account_id
            )
        )

        if refreshed_order is None or refreshed_account is None:
            raise RuntimeError(
                "Failed to reload order or account"
            )

        return OrderFillApplicationResult(
            order_id=refreshed_order.order_id,
            account_id=refreshed_account.account_id,
            trade_id=trade.trade_id,
            order_status=refreshed_order.status_code,
            order_filled_quantity=(
                refreshed_order.filled_quantity
            ),
            order_average_fill_price=(
                refreshed_order.average_fill_price
            ),
            account_available_cash=(
                refreshed_account.available_cash
            ),
            account_realized_profit_loss=(
                refreshed_account.realized_profit_loss
            ),
            symbol=refreshed_order.symbol,
            side=refreshed_order.side,
            fill_quantity=fill_quantity,
            fill_price=fill_price,
            trade_amount=trade.trade_amount,
            trade_realized_profit_loss=(
                trade.realized_profit_loss
            ),
        )
