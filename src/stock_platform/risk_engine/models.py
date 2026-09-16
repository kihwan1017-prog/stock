from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any


class RiskDecisionLevel(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCK = "BLOCK"


class RiskOrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    max_order_amount: Decimal = Decimal("100000")
    max_order_quantity: Decimal = Decimal("1000000")
    max_open_positions: int = 5
    max_investment_ratio: Decimal = Decimal("0.70")
    max_daily_loss: Decimal = Decimal("300000")
    trading_start_time: time = time(9, 0)
    trading_end_time: time = time(15, 20)
    enforce_krx_market_hours: bool = True
    emergency_stop_enabled: bool = False
    allow_sell_during_emergency_stop: bool = True
    max_market_data_age_seconds: int = 30
    max_broker_error_rate: Decimal = Decimal("0.5")
    block_on_stale_market_data: bool = True
    block_on_broker_unstable: bool = True
    # STEP 8-2 — ResolvedRiskPolicy 오버레이 필드
    daily_max_order_amount: Decimal | None = None
    max_total_investment_amount: Decimal | None = None
    max_position_amount: Decimal | None = None
    allow_duplicate_buy: bool = True
    daily_max_loss_rate: Decimal | None = None
    buy_enabled: bool = True
    sell_enabled: bool = True
    sell_only: bool = False
    auto_trading_enabled: bool = True
    account_paused: bool = False
    # STEP 8-7
    daily_order_limit: int = 20
    duplicate_order_window_seconds: int = 5


@dataclass(frozen=True, slots=True)
class RiskOrderRequest:
    exchange_code: str
    symbol: str
    side: RiskOrderSide
    quantity: Decimal
    price: Decimal
    requested_at: datetime
    # Paper: account_id 필수 / LIVE: user_broker_account_id 필수 (XOR)
    account_id: int | None = None
    user_broker_account_id: int | None = None
    # PAPER | LIVE | LIVE_SHADOW | MOCK
    environment: str = "PAPER"
    market_data_age_seconds: int | None = None
    broker_error_rate: Decimal | None = None
    # STEP 8-2
    order_source: str = "MANUAL"  # MANUAL | AUTO | EXIT
    is_risk_reducing: bool = False
    daily_ordered_amount: Decimal = Decimal("0")
    symbol_invested_amount: Decimal = Decimal("0")
    # UPBIT MARKET BUY: 총 KRW (qty*unit_price 대체). None이면 qty*price.
    quote_amount: Decimal | None = None

    @property
    def order_amount(self) -> Decimal:
        if self.quote_amount is not None:
            return Decimal(str(self.quote_amount))
        return self.quantity * self.price

    @property
    def is_live(self) -> bool:
        return str(self.environment or "").upper() in {
            "LIVE",
            "LIVE_SHADOW",
        }

    @property
    def is_paper(self) -> bool:
        return str(self.environment or "").upper() in {
            "PAPER",
            "PAPER_TRADING",
        }

    @property
    def is_mock(self) -> bool:
        return str(self.environment or "").upper() == "MOCK"


@dataclass(frozen=True, slots=True)
class RiskAccountState:
    cash_balance: Decimal
    total_asset_value: Decimal
    invested_amount: Decimal
    daily_realized_profit_loss: Decimal
    daily_unrealized_profit_loss: Decimal
    open_position_count: int
    symbol_position_quantity: Decimal = Decimal("0")
    # 동일 계좌·종목 미체결 SELL (TradingOrder). 신규 position source 아님.
    symbol_pending_sell_quantity: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class RiskRuleResult:
    rule_code: str
    level: RiskDecisionLevel
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RiskEvaluationResult:
    decision: RiskDecisionLevel
    allowed: bool
    evaluated_at: datetime
    order_amount: Decimal
    results: list[RiskRuleResult]
