"""STEP 8-5-16 — Settlement Broker Adapter Protocol / DTO."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol


@dataclass(slots=True)
class SettlementCashSnapshot:
    currency: str = "KRW"
    available: Decimal = Decimal("0")
    locked: Decimal = Decimal("0")
    withdrawable: Decimal | None = None
    buying_power: Decimal | None = None
    total: Decimal | None = None


@dataclass(slots=True)
class SettlementPositionSnapshot:
    exchange_code: str
    symbol: str
    quantity: Decimal
    available_quantity: Decimal | None = None
    locked_quantity: Decimal | None = None
    average_price: Decimal | None = None
    evaluation_price: Decimal | None = None
    evaluation_amount: Decimal | None = None
    unrealized_pnl: Decimal | None = None


@dataclass(slots=True)
class SettlementOrderSnapshot:
    broker_order_id: str | None
    client_identifier: str | None
    symbol: str
    side: str
    status: str
    order_quantity: Decimal
    filled_quantity: Decimal
    order_price: Decimal | None = None


@dataclass(slots=True)
class SettlementExecutionSnapshot:
    broker_execution_id: str
    broker_order_id: str | None
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")


@dataclass(slots=True)
class SettlementBrokerBundle:
    """외부/내부 조회 결과 묶음 (민감 원문 미포함)."""

    broker_code: str
    fetched_at: datetime
    cash: SettlementCashSnapshot
    positions: list[SettlementPositionSnapshot] = field(default_factory=list)
    open_orders: list[SettlementOrderSnapshot] = field(default_factory=list)
    executions: list[SettlementExecutionSnapshot] = field(default_factory=list)
    equity: Decimal | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    sync_ok: bool = True
    sync_error: str | None = None


class AccountSettlementBrokerAdapter(Protocol):
    broker_code: str

    def fetch_bundle(self) -> SettlementBrokerBundle:
        """잔고·포지션·미체결·최근 체결 조회."""
        ...
