"""Canonical EXIT SELL 수량 산정 — broker sellable + strategy-owned + policy cap.

SELL invariant:
  0 < sell_qty <= min(strategy_owned, broker_sellable, max_order_quantity)

MANUAL/UNKNOWN 보유는 STRATEGY_OWNED 합으로 분리한다.
open SELL remaining은 broker_sellable(held - pending)에 이미 반영된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.risk_engine.exit_risk import (
    acquire_exit_sell_scope_lock,
    load_held_quantity,
    load_pending_sell_quantity,
)
from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_OPEN,
    OWNERSHIP_STRATEGY,
    StrategyPositionBindingEntity,
)

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ExitSellQuantityPlan:
    """한 번의 EXIT SELL submit에 쓸 수량 계획."""

    sell_quantity: Decimal
    requested_quantity: Decimal
    broker_held: Decimal
    pending_sell: Decimal
    broker_sellable: Decimal
    strategy_owned: Decimal
    max_order_quantity: Decimal | None
    capped_by: tuple[str, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def state_fingerprint(self) -> str:
        """deterministic reject 재평가용 — 수량 상태 지문."""

        return (
            f"held={self.broker_held}|"
            f"pending={self.pending_sell}|"
            f"sellable={self.broker_sellable}|"
            f"owned={self.strategy_owned}|"
            f"req={self.requested_quantity}|"
            f"max={self.max_order_quantity}"
        )


def load_strategy_owned_open_quantity(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    broker_code: str | None = None,
) -> Decimal:
    """OPEN/PARTIAL_EXIT STRATEGY_OWNED owned_quantity 합 — MANUAL/UNKNOWN 제외."""

    from stock_platform.risk_engine.strategy_owned_entities import (
        BINDING_STATUS_PARTIAL_EXIT,
    )

    sym = str(symbol or "").strip().upper()
    if not sym or not user_broker_account_id:
        return ZERO
    stmt = select(StrategyPositionBindingEntity).where(
        StrategyPositionBindingEntity.user_broker_account_id
        == int(user_broker_account_id),
        StrategyPositionBindingEntity.symbol == sym,
        StrategyPositionBindingEntity.status.in_(
            (BINDING_STATUS_OPEN, BINDING_STATUS_PARTIAL_EXIT)
        ),
        StrategyPositionBindingEntity.ownership_code == OWNERSHIP_STRATEGY,
        StrategyPositionBindingEntity.owned_quantity > ZERO,
    )
    broker = str(broker_code or "").strip().upper()
    if broker:
        stmt = stmt.where(
            StrategyPositionBindingEntity.broker_code == broker
        )
    total = ZERO
    for row in session.scalars(stmt):
        try:
            q = Decimal(str(row.owned_quantity or 0))
        except Exception:  # noqa: BLE001
            q = ZERO
        if q > ZERO:
            total += q
    return total


def resolve_exit_sell_quantity(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    exchange_code: str,
    environment: str,
    broker_code: str | None,
    requested_quantity: Decimal,
    max_order_quantity: Decimal | None,
    require_strategy_owned: bool = True,
) -> ExitSellQuantityPlan:
    """UBA+symbol 잠금 하에서 EXIT SELL 제출 수량을 산정한다.

    require_strategy_owned=True(AUTO): STRATEGY_OWNED 없으면 sell_qty=0.
    """

    sym = str(symbol or "").strip().upper()
    try:
        requested = Decimal(str(requested_quantity))
    except Exception:  # noqa: BLE001
        requested = ZERO
    if requested < ZERO:
        requested = ZERO

    acquire_exit_sell_scope_lock(
        session,
        user_broker_account_id=int(user_broker_account_id),
        paper_account_id=None,
        symbol=sym,
    )

    held = load_held_quantity(
        session,
        symbol=sym,
        exchange_code=exchange_code,
        user_broker_account_id=int(user_broker_account_id),
        paper_account_id=None,
        environment=environment,
    )
    pending = load_pending_sell_quantity(
        session,
        symbol=sym,
        user_broker_account_id=int(user_broker_account_id),
        paper_account_id=None,
        broker_code=broker_code,
    )
    sellable = held - pending
    if sellable < ZERO:
        sellable = ZERO

    owned = load_strategy_owned_open_quantity(
        session,
        user_broker_account_id=int(user_broker_account_id),
        symbol=sym,
        broker_code=broker_code,
    )

    max_qty: Decimal | None = None
    if max_order_quantity is not None:
        try:
            max_qty = Decimal(str(max_order_quantity))
        except Exception:  # noqa: BLE001
            max_qty = None
        if max_qty is not None and max_qty <= ZERO:
            max_qty = None

    caps: list[str] = []
    qty = requested

    if require_strategy_owned:
        if owned <= ZERO:
            return ExitSellQuantityPlan(
                sell_quantity=ZERO,
                requested_quantity=requested,
                broker_held=held,
                pending_sell=pending,
                broker_sellable=sellable,
                strategy_owned=owned,
                max_order_quantity=max_qty,
                capped_by=("NO_STRATEGY_OWNED",),
                detail={"reason": "NO_STRATEGY_OWNED_QUANTITY"},
            )
        if qty > owned:
            qty = owned
            caps.append("STRATEGY_OWNED")
    elif owned > ZERO and qty > owned:
        # 비강제 경로에서도 owned가 있으면 MANUAL 침범 방지
        qty = owned
        caps.append("STRATEGY_OWNED")

    if qty > sellable:
        qty = sellable
        caps.append("BROKER_SELLABLE")

    if max_qty is not None and qty > max_qty:
        qty = max_qty
        caps.append("MAX_ORDER_QUANTITY")

    if qty < ZERO:
        qty = ZERO

    return ExitSellQuantityPlan(
        sell_quantity=qty,
        requested_quantity=requested,
        broker_held=held,
        pending_sell=pending,
        broker_sellable=sellable,
        strategy_owned=owned,
        max_order_quantity=max_qty,
        capped_by=tuple(caps),
        detail={
            "partial_exit": bool(
                caps and qty > ZERO and qty < requested
            ),
        },
    )
