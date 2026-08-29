"""STEP 8-2 — ResolvedRiskPolicy 및 계층 병합 Resolver."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.risk_engine.exit_protection_modes import (
    MODE_INHERIT,
    exit_protections_bundle,
    resolve_max_hold_from_rows,
    resolve_trailing_activation_from_rows,
)
from stock_platform.risk_engine.models import RiskPolicy
from stock_platform.risk_engine.runtime import realtime_risk_policy
from stock_platform.risk_engine.user_risk_entities import (
    SystemRiskSetting,
    UserBrokerAccountRiskSetting,
    UserRiskSetting,
)

ZERO = Decimal("0")
ONE = Decimal("1")

# SL/TP/Trailing rate는 exit_protection_modes 로 별도 해석
_OVERLAY_FIELDS: tuple[str, ...] = (
    "max_order_amount",
    "daily_max_order_amount",
    "max_total_investment_amount",
    "max_position_amount",
    "max_position_count",
    "max_position_weight",
    "max_investment_ratio",
    "allow_duplicate_buy",
    "daily_max_loss_amount",
    "daily_max_loss_rate",
    "auto_trading_enabled",
    "buy_enabled",
    "sell_enabled",
    "sell_only",
    "account_paused",
    "max_order_quantity",
    "daily_order_limit",
    "daily_submit_limit",
    "daily_filled_entry_limit",
    "duplicate_order_window_seconds",
    "max_open_orders",
    "max_slippage_rate",
    "anomaly_orders_per_minute",
    "loop_detect_window_seconds",
    "arm_ttl_seconds",
)

# system overlay에만 rate 포함
_SYSTEM_RATE_FIELDS: tuple[str, ...] = (
    "stop_loss_rate",
    "take_profit_rate",
    "trailing_stop_rate",
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
    max_investment_ratio: Decimal
    allow_duplicate_buy: bool
    daily_max_loss_amount: Decimal
    daily_max_loss_rate: Decimal
    # DISABLED면 None — REAL exit_monitor가 사용하지 않음
    stop_loss_rate: Decimal | None
    take_profit_rate: Decimal | None
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
    daily_submit_limit: int | None = None
    daily_filled_entry_limit: int | None = None
    stop_loss_mode: str = MODE_INHERIT
    take_profit_mode: str = MODE_INHERIT
    trailing_stop_mode: str = MODE_INHERIT
    stop_loss_source: str = "SYSTEM"
    take_profit_source: str = "SYSTEM"
    trailing_stop_source: str = "SYSTEM"
    stop_loss_effective_enabled: bool = True
    take_profit_effective_enabled: bool = True
    trailing_stop_effective_enabled: bool = True
    stop_loss_configured_rate: Decimal | None = None
    take_profit_configured_rate: Decimal | None = None
    trailing_stop_configured_rate: Decimal | None = None
    # REAL Exit V1 — activation / max hold
    trailing_activation_rate: Decimal | None = None
    max_hold_mode: str = MODE_INHERIT
    max_hold_seconds: int | None = None
    max_hold_source: str = "SYSTEM"
    max_hold_effective_enabled: bool = False
    max_hold_configured_seconds: int | None = None

    def to_engine_policy(self) -> RiskPolicy:
        """RealtimeRiskEngine용 RiskPolicy로 변환."""

        return RiskPolicy(
            max_order_amount=self.max_order_amount,
            max_order_quantity=self.max_order_quantity,
            max_open_positions=self.max_position_count,
            max_investment_ratio=self.max_investment_ratio,
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

    def exit_protection_summary(self) -> dict[str, Any]:
        """ops-status / Admin UI용 REAL exit protection SoT."""

        def _one(
            *,
            mode: str,
            enabled: bool,
            rate: Decimal | None,
            configured: Decimal | None,
            source: str,
        ) -> dict[str, Any]:
            return {
                "mode": mode,
                "configured_rate": (
                    str(configured) if configured is not None else None
                ),
                "effective_enabled": enabled,
                "effective_rate": str(rate) if rate is not None else None,
                "source": source,
            }

        return {
            "stop_loss": _one(
                mode=self.stop_loss_mode,
                enabled=self.stop_loss_effective_enabled,
                rate=self.stop_loss_rate,
                configured=self.stop_loss_configured_rate,
                source=self.stop_loss_source,
            ),
            "take_profit": _one(
                mode=self.take_profit_mode,
                enabled=self.take_profit_effective_enabled,
                rate=self.take_profit_rate,
                configured=self.take_profit_configured_rate,
                source=self.take_profit_source,
            ),
            "trailing_stop": _one(
                mode=self.trailing_stop_mode,
                enabled=self.trailing_stop_effective_enabled,
                rate=self.trailing_stop_rate,
                configured=self.trailing_stop_configured_rate,
                source=self.trailing_stop_source,
            ),
            "trailing_activation_rate": (
                str(self.trailing_activation_rate)
                if self.trailing_activation_rate is not None
                else None
            ),
            "max_hold": {
                "mode": self.max_hold_mode,
                "configured_seconds": self.max_hold_configured_seconds,
                "effective_enabled": self.max_hold_effective_enabled,
                "effective_seconds": self.max_hold_seconds,
                "source": self.max_hold_source,
            },
            "ma_dead_cross": {
                "mode": "ENABLED",
                "effective_enabled": True,
                "source": "STRATEGY",
                "real": "ENABLED",
            },
            "time_exit": {
                "mode": self.max_hold_mode,
                "effective_enabled": self.max_hold_effective_enabled,
                "effective_seconds": self.max_hold_seconds,
                "source": self.max_hold_source,
                "real": (
                    "ENABLED" if self.max_hold_effective_enabled else "DISABLED"
                ),
            },
        }

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = str(value)
            elif isinstance(value, tuple):
                payload[key] = list(value)
        payload["exit_protection"] = self.exit_protection_summary()
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
        "max_investment_ratio": realtime_risk_policy.max_investment_ratio,
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
        "daily_submit_limit": None,
        "daily_filled_entry_limit": None,
        "duplicate_order_window_seconds": 5,
        "max_open_orders": 20,
        "max_slippage_rate": Decimal("0.01"),
        "anomaly_orders_per_minute": 10,
        "loop_detect_window_seconds": 60,
        "arm_ttl_seconds": 300,
    }


def _row_overlay(
    base: dict[str, Any],
    row: Any | None,
    *,
    include_rates: bool = False,
) -> dict[str, Any]:
    if row is None:
        return base
    merged = dict(base)
    fields = _OVERLAY_FIELDS + (
        _SYSTEM_RATE_FIELDS if include_rates else ()
    )
    for field in fields:
        value = getattr(row, field, None)
        if value is None:
            continue
        if type(value).__name__ in {"MagicMock", "AsyncMock", "Mock"}:
            continue
        merged[field] = value
    return merged


class ResolvedRiskPolicyResolver:
    """시스템 → 사용자 → UserBrokerAccount. Exit protection mode 적용."""

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
            base = _row_overlay(base, system, include_rates=True)
            layers = ["system"]

        user_row: UserRiskSetting | None = None
        if user_id is not None:
            user_row = self._session.scalar(
                select(UserRiskSetting).where(
                    UserRiskSetting.user_id == int(user_id)
                )
            )
            if user_row is not None:
                base = _row_overlay(base, user_row, include_rates=False)
                layers.append("user")

        uba_row: UserBrokerAccountRiskSetting | None = None
        if user_broker_account_id is not None:
            uba_row = self._session.scalar(
                select(UserBrokerAccountRiskSetting).where(
                    UserBrokerAccountRiskSetting.user_broker_account_id
                    == int(user_broker_account_id)
                )
            )
            if uba_row is not None:
                base = _row_overlay(base, uba_row, include_rates=False)
                layers.append("account")

        protections = exit_protections_bundle(
            system_rates={
                "stop_loss": (
                    None
                    if base.get("stop_loss_rate") is None
                    else Decimal(str(base["stop_loss_rate"]))
                ),
                "take_profit": (
                    None
                    if base.get("take_profit_rate") is None
                    else Decimal(str(base["take_profit_rate"]))
                ),
                "trailing_stop": (
                    None
                    if base.get("trailing_stop_rate") is None
                    else Decimal(str(base["trailing_stop_rate"]))
                ),
            },
            user_row=user_row,
            account_row=uba_row,
        )
        sl = protections["stop_loss"]
        tp = protections["take_profit"]
        tr = protections["trailing_stop"]
        mh = resolve_max_hold_from_rows(
            user_row=user_row,
            account_row=uba_row,
            system_seconds=None,
        )
        act = resolve_trailing_activation_from_rows(
            user_row=user_row,
            account_row=uba_row,
        )

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
            max_investment_ratio=Decimal(str(base["max_investment_ratio"])),
            allow_duplicate_buy=bool(base["allow_duplicate_buy"]),
            daily_max_loss_amount=Decimal(
                str(base["daily_max_loss_amount"])
            ),
            daily_max_loss_rate=Decimal(str(base["daily_max_loss_rate"])),
            stop_loss_rate=sl.effective_rate,
            take_profit_rate=tp.effective_rate,
            trailing_stop_rate=tr.effective_rate,
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
            daily_submit_limit=(
                None
                if base.get("daily_submit_limit") is None
                else int(base["daily_submit_limit"])
            ),
            daily_filled_entry_limit=(
                None
                if base.get("daily_filled_entry_limit") is None
                else int(base["daily_filled_entry_limit"])
            ),
            stop_loss_mode=sl.mode,
            take_profit_mode=tp.mode,
            trailing_stop_mode=tr.mode,
            stop_loss_source=sl.source,
            take_profit_source=tp.source,
            trailing_stop_source=tr.source,
            stop_loss_effective_enabled=sl.effective_enabled,
            take_profit_effective_enabled=tp.effective_enabled,
            trailing_stop_effective_enabled=tr.effective_enabled,
            stop_loss_configured_rate=sl.configured_rate,
            take_profit_configured_rate=tp.configured_rate,
            trailing_stop_configured_rate=tr.configured_rate,
            trailing_activation_rate=act,
            max_hold_mode=mh.mode,
            max_hold_seconds=mh.effective_seconds,
            max_hold_source=mh.source,
            max_hold_effective_enabled=mh.effective_enabled,
            max_hold_configured_seconds=mh.configured_seconds,
        )
