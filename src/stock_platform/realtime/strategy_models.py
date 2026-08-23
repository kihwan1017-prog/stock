from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class RealtimeSignalAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


# 일봉 계약으로 취급할 LIVE timeframe 표기
_DAILY_TIMEFRAMES = frozenset({"1D", "D", "DAY", "DAILY"})


def normalize_realtime_timeframe(raw: str | None) -> str:
    """전략 payload timeframe을 대문자 정규화한다."""

    return str(raw or "").strip().upper()


def uses_daily_bars(timeframe: str | None) -> bool:
    """1D 전략인지 여부. 빈 값/틱 전략은 False."""

    return normalize_realtime_timeframe(timeframe) in _DAILY_TIMEFRAMES


@dataclass(frozen=True, slots=True)
class RealtimeStrategyConfig:
    short_window: int = 5
    long_window: int = 20
    minimum_change_rate: Decimal = Decimal("0")
    stop_loss_ratio: Decimal = Decimal("0.03")
    take_profit_ratio: Decimal = Decimal("0.06")
    cooldown_seconds: int = 30
    # 전략 compiled timeframe. 빈 값이면 레거시 raw tick MA.
    timeframe: str = ""
    # Paper/Backtest cooldown_bars. LIVE 초 단위 cooldown과 별개 — 이번 STEP에서 변경하지 않음.
    cooldown_bars: int | None = None
    # Portfolio entry: CROSS_EVENT(기본) | BULLISH_STATE — FIXED는 항상 CROSS_EVENT
    entry_signal_policy: str = "CROSS_EVENT"
    portfolio_mode: bool = False
    # MA_DEAD_CROSS anti-churn (보호 청산 미적용)
    exit_min_ma_separation_pct: float = 0.03
    ma_exit_min_holding_seconds: int = 180
    estimated_fee_rate: float = 0.0005

    def uses_daily_bars(self) -> bool:
        return uses_daily_bars(self.timeframe)


@dataclass(frozen=True, slots=True)
class RealtimePositionState:
    quantity: Decimal
    average_entry_price: Decimal | None
    opened_at: datetime | None = None
    buy_fee: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RealtimeSignal:
    exchange_code: str
    symbol: str
    action: RealtimeSignalAction
    signal_price: Decimal
    short_average: Decimal | None
    long_average: Decimal | None
    change_rate: Decimal | None
    reason_code: str
    generated_at: datetime
    # STEP 8-5-9 — Scope 메타 (레거시 신호는 None)
    signal_id: str | None = None
    fingerprint: str | None = None
    scope_key: str | None = None
    user_id: int | None = None
    account_kind: str | None = None
    account_id: int | None = None
    strategy_id: int | None = None
    strategy_version: str | None = None
    broker_code: str | None = None
    market_type: str | None = None
    user_broker_account_id: int | None = None
    source_code: str | None = None
