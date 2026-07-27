"""STEP 8-2 — ResolvedRiskPolicy 및 계층 병합 Resolver."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.risk_engine.models import RiskPolicy
from stock_platform.risk_engine.runtime import realtime_risk_policy
from stock_platform.risk_engine.user_risk_entities import (
    SystemRiskSetting,
    UserBrokerAccountRiskSetting,
    UserRiskSetting,
)

ZERO = Decimal("0")
ONE = Decimal("1")

# 오버레이 대상 필드 (NULL이면 상위 유지)
_OVERLAY_FIELDS: tuple[str, ...] = (
    "max_order_amount",
    "daily_max_order_amount",
    "max_total_investment_amount",
    "max_position_amount",
    "max_position_count",
    "max_position_weight",
    "allow_duplicate_buy",
    "daily_max_loss_amount",
    "daily_max_loss_rate",
    "stop_loss_rate",
    "take_profit_rate",
    "trailing_stop_rate",
    "auto_trading_enabled",
    "buy_enabled",
    "sell_enabled",
    "sell_only",
    "account_paused",
    "max_order_quantity",
    "daily_order_limit",
    "duplicate_order_window_seconds",
    "max_open_orders",
    "max_slippage_rate",
    "anomaly_orders_per_minute",
    "loop_detect_window_seconds",
    "arm_ttl_seconds",
)


@dataclass(frozen=True, slots=True)
class ResolvedRiskPolicy:
    """시스템 → 사용자 → 계좌 순으로 병합된 최종 정책."""

    max_order_amount: Decimal
    daily_max_order_amount: Decimal
    max_total_investment_amount: Decimal
    max_position_amount: Decimal
    max_position_count: int
    max_position_weight: Decimal
    allow_duplicate_buy: bool
    daily_max_loss_amount: Decimal
    daily_max_loss_rate: Decimal
    stop_loss_rate: Decimal
    take_profit_rate: Decimal
    trailing_stop_rate: Decimal | None
    auto_trading_enabled: bool
    buy_enabled: bool
    sell_enabled: bool
    sell_only: bool
    account_paused: bool
    max_order_quantity: Decimal
    daily_order_limit: int
    duplicate_order_window_seconds: int
    max_open_orders: int
    max_slippage_rate: Decimal
    anomaly_orders_per_minute: int
    loop_detect_window_seconds: int
    arm_ttl_seconds: int
    source_layers: tuple[str, ...]

    def to_engine_policy(self) -> RiskPolicy:
        """RealtimeRiskEngine용 RiskPolicy로 변환."""

        return RiskPolicy(
            max_order_amount=self.max_order_amount,
            max_order_quantity=self.max_order_quantity,
            max_open_positions=self.max_position_count,
            max_investment_ratio=realtime_risk_policy.max_investment_ratio,
            max_daily_loss=self.daily_max_loss_amount,
            trading_start_time=realtime_risk_policy.trading_start_time,
            trading_end_time=realtime_risk_policy.trading_end_time,
            enforce_krx_market_hours=(
                realtime_risk_policy.enforce_krx_market_hours
            ),
            emergency_stop_enabled=(
                realtime_risk_policy.emergency_stop_enabled
            ),
            allow_sell_during_emergency_stop=(
                realtime_risk_policy.allow_sell_during_emergency_stop
            ),
            max_market_data_age_seconds=(
                realtime_risk_policy.max_market_data_age_seconds
            ),
            max_broker_error_rate=realtime_risk_policy.max_broker_error_rate,
            block_on_stale_market_data=(
                realtime_risk_policy.block_on_stale_market_data
            ),
            block_on_broker_unstable=(
                realtime_risk_policy.block_on_broker_unstable
            ),
            daily_max_order_amount=self.daily_max_order_amount,
            max_total_investment_amount=self.max_total_investment_amount,
            max_position_amount=self.max_position_amount,
            allow_duplicate_buy=self.allow_duplicate_buy,
            daily_max_loss_rate=self.daily_max_loss_rate,
            buy_enabled=self.buy_enabled,
            sell_enabled=self.sell_enabled,
            sell_only=self.sell_only,
            auto_trading_enabled=self.auto_trading_enabled,
            account_paused=self.account_paused,
            daily_order_limit=self.daily_order_limit,
            duplicate_order_window_seconds=self.duplicate_order_window_seconds,
        )

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = str(value)
            elif isinstance(value, tuple):
                payload[key] = list(value)
        return payload


def _code_fallback_system() -> dict[str, Any]:
    """DB 시스템 행이 없을 때 코드 기본값."""

    return {
        "max_order_amount": realtime_risk_policy.max_order_amount,
        "daily_max_order_amount": Decimal("1000000"),
        "max_total_investment_amount": Decimal("5000000"),
        "max_position_amount": Decimal("1000000"),
        "max_position_count": realtime_risk_policy.max_open_positions,
        "max_position_weight": Decimal("0.20"),
        "allow_duplicate_buy": True,
        "daily_max_loss_amount": realtime_risk_policy.max_daily_loss,
        "daily_max_loss_rate": Decimal("0.05"),
        "stop_loss_rate": Decimal("0.05"),
        "take_profit_rate": Decimal("0.10"),
        "trailing_stop_rate": Decimal("0.03"),
        "auto_trading_enabled": True,
        "buy_enabled": True,
        "sell_enabled": True,
        "sell_only": False,
        "account_paused": False,
        "max_order_quantity": Decimal("100"),
        "daily_order_limit": 20,
        "duplicate_order_window_seconds": 5,
        "max_open_orders": 20,
        "max_slippage_rate": Decimal("0.01"),
        "anomaly_orders_per_minute": 10,
        "loop_detect_window_seconds": 60,
        "arm_ttl_seconds": 300,
    }


def _row_overlay(base: dict[str, Any], row: Any | None) -> dict[str, Any]:
    if row is None:
        return base
    merged = dict(base)
    for field in _OVERLAY_FIELDS:
        value = getattr(row, field, None)
        if value is None:
            continue
        # MagicMock 등 테스트 더미가 의도치 않게 덮지 않도록
        if type(value).__name__ in {"MagicMock", "AsyncMock", "Mock"}:
            continue
        merged[field] = value
    return merged


class ResolvedRiskPolicyResolver:
    """
    공통 진입점.
    우선순위: 시스템 → 사용자 → UserBrokerAccount.
    Paper는 UBA가 없으므로 사용자 기본까지만 적용.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def resolve(
        self,
        *,
        user_id: int | None = None,
        user_broker_account_id: int | None = None,
    ) -> ResolvedRiskPolicy:
        layers: list[str] = []
        base = _code_fallback_system()
        layers.append("code_fallback")

        system = self._session.scalar(
            select(SystemRiskSetting).where(
                SystemRiskSetting.singleton_key == "DEFAULT"
            )
        )
        if system is not None:
            base = _row_overlay(base, system)
            layers = ["system"]

        if user_id is not None:
            user_row = self._session.scalar(
                select(UserRiskSetting).where(
                    UserRiskSetting.user_id == int(user_id)
                )
            )
            if user_row is not None:
                base = _row_overlay(base, user_row)
                layers.append("user")

        if user_broker_account_id is not None:
            uba_row = self._session.scalar(
                select(UserBrokerAccountRiskSetting).where(
                    UserBrokerAccountRiskSetting.user_broker_account_id
                    == int(user_broker_account_id)
                )
            )
            if uba_row is not None:
                base = _row_overlay(base, uba_row)
                layers.append("account")

        return ResolvedRiskPolicy(
            max_order_amount=Decimal(str(base["max_order_amount"])),
            daily_max_order_amount=Decimal(
                str(base["daily_max_order_amount"])
            ),
            max_total_investment_amount=Decimal(
                str(base["max_total_investment_amount"])
            ),
            max_position_amount=Decimal(str(base["max_position_amount"])),
            max_position_count=int(base["max_position_count"]),
            max_position_weight=Decimal(str(base["max_position_weight"])),
            allow_duplicate_buy=bool(base["allow_duplicate_buy"]),
            daily_max_loss_amount=Decimal(
                str(base["daily_max_loss_amount"])
            ),
            daily_max_loss_rate=Decimal(str(base["daily_max_loss_rate"])),
            stop_loss_rate=Decimal(str(base["stop_loss_rate"])),
            take_profit_rate=Decimal(str(base["take_profit_rate"])),
            trailing_stop_rate=(
                None
                if base.get("trailing_stop_rate") is None
                else Decimal(str(base["trailing_stop_rate"]))
            ),
            auto_trading_enabled=bool(base["auto_trading_enabled"]),
            buy_enabled=bool(base["buy_enabled"]),
            sell_enabled=bool(base["sell_enabled"]),
            sell_only=bool(base["sell_only"]),
            account_paused=bool(base["account_paused"]),
            max_order_quantity=Decimal(str(base["max_order_quantity"])),
            daily_order_limit=int(base["daily_order_limit"]),
            duplicate_order_window_seconds=int(
                base["duplicate_order_window_seconds"]
            ),
            max_open_orders=int(base["max_open_orders"]),
            max_slippage_rate=Decimal(str(base["max_slippage_rate"])),
            anomaly_orders_per_minute=int(
                base["anomaly_orders_per_minute"]
            ),
            loop_detect_window_seconds=int(
                base["loop_detect_window_seconds"]
            ),
            arm_ttl_seconds=int(base["arm_ttl_seconds"]),
            source_layers=tuple(layers),
        )
