from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
    PaperTrade,
)
from stock_platform.trading.account_repository import (
    PaperAccountRepository,
)
from stock_platform.trading.models import OrderSide


ZERO = Decimal("0")


class PaperAccountError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PositionValuation:
    exchange_code: str
    symbol: str
    quantity: Decimal
    average_entry_price: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_profit_loss: Decimal
    unrealized_return_rate: Decimal


@dataclass(frozen=True, slots=True)
class AccountValuation:
    account_id: int
    available_cash: Decimal
    position_market_value: Decimal
    total_equity: Decimal
    realized_profit_loss: Decimal
    unrealized_profit_loss: Decimal
    positions: list[PositionValuation]


class PaperAccountService:
    """모의 계좌 현금, 포지션, 손익을 관리한다."""

    def __init__(
        self,
        repository: PaperAccountRepository,
    ) -> None:
        self._repository = repository

    def create_account(
        self,
        *,
        account_name: str,
        initial_cash: Decimal,
        currency_code: str = "KRW",
        user_id: int | None = None,
    ) -> PaperAccount:
        if not account_name.strip():
            raise PaperAccountError(
                "account_name is required"
            )
        if initial_cash <= ZERO:
            raise PaperAccountError(
                "initial_cash must be greater than zero"
            )

        return self._repository.save_account(
            PaperAccount(
                account_name=account_name.strip(),
                currency_code=currency_code.upper(),
                initial_cash=initial_cash,
                available_cash=initial_cash,
                realized_profit_loss=ZERO,
                user_id=user_id,
            )
        )

    def apply_fill(
        self,
        *,
        account_id: int,
        exchange_code: str,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        fill_price: Decimal,
        order_id: int | None = None,
    ) -> PaperTrade:
        if quantity <= ZERO:
            raise PaperAccountError(
                "quantity must be greater than zero"
            )
        if fill_price <= ZERO:
            raise PaperAccountError(
                "fill_price must be greater than zero"
            )

        account = self._repository.get_account(
            account_id
        )
        if account is None:
            raise LookupError(
                f"Paper account not found: {account_id}"
            )

        exchange = exchange_code.upper()
        normalized_symbol = symbol.upper()
        trade_amount = (
            quantity * fill_price
        ).quantize(Decimal("0.01"))

        position = self._repository.get_position(
            account_id=account_id,
            exchange_code=exchange,
            symbol=normalized_symbol,
        )

        realized_profit_loss = ZERO

        if side == OrderSide.BUY:
            if account.available_cash < trade_amount:
                raise PaperAccountError(
                    "available_cash is insufficient"
                )

            if position is None:
                position = PaperPosition(
                    account_id=account_id,
                    exchange_code=exchange,
                    symbol=normalized_symbol,
                    quantity=ZERO,
                    average_entry_price=ZERO,
                    highest_price=fill_price,
                    realized_profit_loss=ZERO,
                )

            previous_amount = (
                position.quantity
                * position.average_entry_price
            )
            new_quantity = position.quantity + quantity

            position.average_entry_price = (
                (previous_amount + trade_amount)
                / new_quantity
            ).quantize(Decimal("0.00000001"))
            position.quantity = new_quantity
            position.highest_price = max(
                position.highest_price,
                fill_price,
            )
            account.available_cash -= trade_amount

        elif side == OrderSide.SELL:
            if position is None or position.quantity < quantity:
                raise PaperAccountError(
                    "position quantity is insufficient"
                )

            realized_profit_loss = (
                (fill_price - position.average_entry_price)
                * quantity
            ).quantize(Decimal("0.01"))

            position.quantity -= quantity
            position.realized_profit_loss += (
                realized_profit_loss
            )
            account.realized_profit_loss += (
                realized_profit_loss
            )
            account.available_cash += trade_amount

            if position.quantity == ZERO:
                position.average_entry_price = ZERO
                position.highest_price = ZERO
        else:
            raise PaperAccountError(
                f"Unsupported side: {side}"
            )

        self._repository.save_position(position)

        trade = PaperTrade(
            account_id=account_id,
            order_id=order_id,
            exchange_code=exchange,
            symbol=normalized_symbol,
            side=side.value,
            quantity=quantity,
            fill_price=fill_price,
            trade_amount=trade_amount,
            realized_profit_loss=realized_profit_loss,
        )

        return self._repository.save_trade(trade)

    def value_account(
        self,
        *,
        account_id: int,
        prices: dict[str, Decimal],
    ) -> AccountValuation:
        account = self._repository.get_account(account_id)
        if account is None:
            raise LookupError(
                f"Paper account not found: {account_id}"
            )

        positions = self._repository.list_positions(
            account_id=account_id
        )

        values: list[PositionValuation] = []
        total_market_value = ZERO
        total_unrealized = ZERO

        for position in positions:
            key = (
                f"{position.exchange_code}:"
                f"{position.symbol}"
            )
            current_price = prices.get(key)

            if current_price is None:
                raise PaperAccountError(
                    f"Current price is missing: {key}"
                )
            if current_price <= ZERO:
                raise PaperAccountError(
                    f"Current price must be positive: {key}"
                )

            if current_price > position.highest_price:
                position.highest_price = current_price

            market_value = (
                position.quantity * current_price
            ).quantize(Decimal("0.01"))

            cost_value = (
                position.quantity
                * position.average_entry_price
            ).quantize(Decimal("0.01"))

            unrealized = (
                market_value - cost_value
            ).quantize(Decimal("0.01"))

            return_rate = (
                unrealized / cost_value * Decimal("100")
                if cost_value > ZERO
                else ZERO
            ).quantize(Decimal("0.0001"))

            values.append(
                PositionValuation(
                    exchange_code=position.exchange_code,
                    symbol=position.symbol,
                    quantity=position.quantity,
                    average_entry_price=(
                        position.average_entry_price
                    ),
                    current_price=current_price,
                    market_value=market_value,
                    unrealized_profit_loss=unrealized,
                    unrealized_return_rate=return_rate,
                )
            )

            total_market_value += market_value
            total_unrealized += unrealized

        self._repository.commit()

        total_equity = (
            account.available_cash
            + total_market_value
        ).quantize(Decimal("0.01"))

        return AccountValuation(
            account_id=account.account_id,
            available_cash=account.available_cash,
            position_market_value=(
                total_market_value.quantize(
                    Decimal("0.01")
                )
            ),
            total_equity=total_equity,
            realized_profit_loss=(
                account.realized_profit_loss
            ),
            unrealized_profit_loss=(
                total_unrealized.quantize(
                    Decimal("0.01")
                )
            ),
            positions=values,
        )
