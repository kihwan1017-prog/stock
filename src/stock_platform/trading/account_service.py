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
        is_default: bool = False,
        is_active: bool = True,
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
                is_default=is_default,
                is_active=is_active,
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

        prov_kwargs: dict = {}
        if order_id is not None:
            try:
                from stock_platform.trading.models import PaperOrder
                from stock_platform.trading.order_strategy_provenance import (
                    provenance_from_order_entity,
                )

                paper_order = self._repository._session.get(PaperOrder, order_id)
                if paper_order is not None:
                    prov_kwargs = provenance_from_order_entity(
                        paper_order
                    ).as_column_kwargs()
            except Exception:  # noqa: BLE001
                prov_kwargs = {}

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
            **prov_kwargs,
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

    def soft_delete_account(
        self,
        account_id: int,
        *,
        allow_default: bool = False,
    ) -> dict:
        """
        Soft Delete (deleted_at).

        - Hard Delete(행 삭제)는 수행하지 않음
        - 주문/체결 이력이 있어도 Soft Delete만 허용
        - 이미 삭제된 계좌는 LookupError
        """

        account = self._repository.get_account(
            account_id,
            include_deleted=True,
        )
        if account is None:
            raise LookupError(f"Paper account not found: {account_id}")
        if account.deleted_at is not None:
            raise PaperAccountError(
                f"이미 삭제된 Paper 계좌입니다: {account_id}"
            )
        if account.is_default and not allow_default:
            raise PaperAccountError(
                "기본 Paper 계좌는 삭제할 수 없습니다. "
                "다른 계좌를 기본으로 지정한 뒤 다시 시도하세요."
            )

        has_history = self._repository.has_order_or_trade_history(
            account_id
        )
        # 이력이 있어도 Soft Delete만 — Hard Delete 경로 없음
        self._repository.soft_delete_account(account)
        self._repository.commit()

        return {
            "deleted": True,
            "account_id": int(account.account_id),
            "mode": "soft_delete",
            "deleted_at": account.deleted_at.isoformat()
            if account.deleted_at
            else None,
            "has_trading_history": has_history,
            "hard_delete_allowed": False,
        }

    def update_account(
        self,
        account_id: int,
        *,
        account_name: str | None = None,
        is_active: bool | None = None,
        is_default: bool | None = None,
        initial_cash: Decimal | None = None,
        fields_set: set[str] | None = None,
    ) -> tuple[PaperAccount, list[dict]]:
        """
        Soft-deleted 제외. 부분 수정.
        반환: (갱신된 계좌, 변경 내역 [{field, before, after}, ...])
        """

        provided = fields_set if fields_set is not None else {
            name
            for name, value in (
                ("account_name", account_name),
                ("is_active", is_active),
                ("is_default", is_default),
                ("initial_cash", initial_cash),
            )
            if value is not None
        }
        if not provided:
            raise PaperAccountError("수정할 필드가 없습니다.")

        account = self._repository.get_account(account_id)
        if account is None:
            raise LookupError(f"Paper account not found: {account_id}")
        if account.deleted_at is not None:
            raise PaperAccountError(
                f"삭제된 Paper 계좌는 수정할 수 없습니다: {account_id}"
            )

        changes: list[dict] = []

        if "account_name" in provided:
            if account_name is None:
                raise PaperAccountError("account_name is required")
            name = account_name.strip()
            if not name:
                raise PaperAccountError("계좌명은 공백만 입력할 수 없습니다.")
            if len(name) > 100:
                raise PaperAccountError("계좌명은 최대 100자입니다.")
            conflict = self._repository.find_by_account_name(
                name,
                exclude_account_id=account_id,
            )
            if conflict is not None:
                raise PaperAccountError(
                    f"이미 사용 중인 계좌명입니다: {name}"
                )
            if name != account.account_name:
                changes.append(
                    {
                        "field": "account_name",
                        "before": account.account_name,
                        "after": name,
                    }
                )
                account.account_name = name

        if "is_active" in provided and is_active is not None:
            if bool(is_active) != bool(account.is_active):
                changes.append(
                    {
                        "field": "is_active",
                        "before": bool(account.is_active),
                        "after": bool(is_active),
                    }
                )
                account.is_active = bool(is_active)
                if not is_active and account.is_default:
                    changes.append(
                        {
                            "field": "is_default",
                            "before": True,
                            "after": False,
                        }
                    )
                    account.is_default = False

        if "is_default" in provided and is_default is not None:
            want_default = bool(is_default)
            if want_default and not account.is_active:
                raise PaperAccountError(
                    "비활성 계좌는 기본 계좌로 지정할 수 없습니다."
                )
            if want_default != bool(account.is_default):
                if want_default and account.user_id is not None:
                    self._repository.clear_defaults_for_user(
                        int(account.user_id),
                        exclude_account_id=account_id,
                    )
                changes.append(
                    {
                        "field": "is_default",
                        "before": bool(account.is_default),
                        "after": want_default,
                    }
                )
                account.is_default = want_default

        if "initial_cash" in provided:
            if initial_cash is None:
                raise PaperAccountError("initial_cash is required")
            if initial_cash <= ZERO:
                raise PaperAccountError(
                    "초기 자산은 0보다 커야 합니다."
                )
            has_activity = self._repository.has_trading_activity(
                account_id
            )
            if has_activity:
                raise PaperAccountError(
                    "주문·체결·보유 이력이 있는 계좌는 "
                    "초기 자산을 수정할 수 없습니다."
                )
            new_cash = initial_cash.quantize(Decimal("0.01"))
            if new_cash != account.initial_cash:
                changes.append(
                    {
                        "field": "initial_cash",
                        "before": str(account.initial_cash),
                        "after": str(new_cash),
                    }
                )
                # 거래 없는 신규 계좌 — 가용 현금도 동일하게 맞춤
                if account.available_cash != new_cash:
                    changes.append(
                        {
                            "field": "available_cash",
                            "before": str(account.available_cash),
                            "after": str(new_cash),
                        }
                    )
                account.initial_cash = new_cash
                account.available_cash = new_cash

        if not changes:
            # 전달은 됐으나 값이 동일 — 성공으로 간주 (변경 없음)
            return account, []

        self._repository.persist_account(account)
        self._repository.commit()
        return account, changes
