from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class DashboardAccountSummary:
    account_id: int
    cash_balance: Decimal
    realized_profit_loss: Decimal
    open_position_count: int
    total_position_value: Decimal


@dataclass(frozen=True, slots=True)
class DashboardTradingSummary:
    today_order_count: int
    today_trade_count: int
    recent_orders: list[dict[str, Any]]
    recent_trades: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RealtimeDashboardSnapshot:
    generated_at: datetime
    application: dict[str, Any]
    infrastructure: dict[str, Any]
    realtime: dict[str, Any]
    account: DashboardAccountSummary | None
    trading: DashboardTradingSummary
    ai: dict[str, Any]
    recent_errors: list[dict[str, Any]]
