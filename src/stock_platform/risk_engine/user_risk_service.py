"""STEP 8-2 — 리스크 설정 CRUD Service."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.risk_engine.resolved_policy import (
    ResolvedRiskPolicy,
    ResolvedRiskPolicyResolver,
)
from stock_platform.risk_engine.user_risk_entities import (
    SystemRiskSetting,
    UserBrokerAccountRiskSetting,
    UserRiskSetting,
)

_AMOUNT_FIELDS = frozenset(
    {
        "max_order_amount",
        "daily_max_order_amount",
        "max_total_investment_amount",
        "max_position_amount",
        "daily_max_loss_amount",
        "max_order_quantity",
    }
)
_RATE_FIELDS = frozenset(
    {
        "max_position_weight",
        "max_investment_ratio",
        "daily_max_loss_rate",
        "stop_loss_rate",
        "take_profit_rate",
        "trailing_stop_rate",
        "max_slippage_rate",
    }
)
_BOOL_FIELDS = frozenset(
    {
        "allow_duplicate_buy",
        "auto_trading_enabled",
        "buy_enabled",
        "sell_enabled",
        "sell_only",
        "account_paused",
    }
)
_INT_FIELDS = frozenset(
    {
        "max_position_count",
        "daily_order_limit",
        "daily_submit_limit",
        "daily_filled_entry_limit",
        "duplicate_order_window_seconds",
        "max_open_orders",
        "anomaly_orders_per_minute",
        "loop_detect_window_seconds",
        "arm_ttl_seconds",
    }
)
_ALL_FIELDS = (
    _AMOUNT_FIELDS | _RATE_FIELDS | _BOOL_FIELDS | _INT_FIELDS
)


class RiskSettingValidationError(ValueError):
    """API 400/422용 검증 오류."""


def validate_risk_payload(
    payload: dict[str, Any],
    *,
    allow_null: bool = True,
) -> dict[str, Any]:
    """금액·비율·플래그 검증. 비율은 fraction(0~1)."""

    cleaned: dict[str, Any] = {}
    for key, raw in payload.items():
        if key not in _ALL_FIELDS:
            continue
        if raw is None:
            if allow_null:
                cleaned[key] = None
            continue
        if key in _AMOUNT_FIELDS:
            amount = Decimal(str(raw))
            if amount < 0:
                raise RiskSettingValidationError(
                    f"{key} must be >= 0"
                )
            cleaned[key] = amount
        elif key in _RATE_FIELDS:
            rate = Decimal(str(raw))
            if rate < 0 or rate > 1:
                raise RiskSettingValidationError(
                    f"{key} must be between 0 and 1 (fraction)"
                )
            cleaned[key] = rate
        elif key in _INT_FIELDS:
            count = int(raw)
            if count < 0:
                raise RiskSettingValidationError(
                    f"{key} must be >= 0"
                )
            cleaned[key] = count
        elif key in _BOOL_FIELDS:
            cleaned[key] = bool(raw)

    stop = cleaned.get("stop_loss_rate")
    take = cleaned.get("take_profit_rate")
    # 둘 다 명시된 경우에만 교차 검증 (의도 뒤집힘 방지 힌트)
    if (
        isinstance(stop, Decimal)
        and isinstance(take, Decimal)
        and stop > 0
        and take > 0
        and stop >= take
    ):
        raise RiskSettingValidationError(
            "stop_loss_rate must be less than take_profit_rate"
        )

    sell_only = cleaned.get("sell_only")
    buy_enabled = cleaned.get("buy_enabled")
    if sell_only is True and buy_enabled is True:
        # sell_only 가 우선 — buy_enabled 를 강제 False
        cleaned["buy_enabled"] = False

    return cleaned


def _snapshot_row(row: Any | None) -> dict[str, Any]:
    if row is None:
        return {}
    out: dict[str, Any] = {}
    for field in _ALL_FIELDS:
        value = getattr(row, field, None)
        if isinstance(value, Decimal):
            out[field] = str(value)
        else:
            out[field] = value
    return out


class UserRiskSettingService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._resolver = ResolvedRiskPolicyResolver(session)

    def get_system(self) -> SystemRiskSetting:
        row = self._session.scalar(
            select(SystemRiskSetting).where(
                SystemRiskSetting.singleton_key == "DEFAULT"
            )
        )
        if row is None:
            raise LookupError("system risk setting missing")
        return row

    def update_system(
        self,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> SystemRiskSetting:
        cleaned = validate_risk_payload(payload, allow_null=False)
        row = self.get_system()
        for key, value in cleaned.items():
            if value is not None:
                setattr(row, key, value)
        row.updated_by = actor
        self._session.flush()
        return row

    def get_user_row(self, user_id: int) -> UserRiskSetting | None:
        return self._session.scalar(
            select(UserRiskSetting).where(
                UserRiskSetting.user_id == int(user_id)
            )
        )

    def upsert_user(
        self,
        user_id: int,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> UserRiskSetting:
        cleaned = validate_risk_payload(payload, allow_null=True)
        row = self.get_user_row(user_id)
        if row is None:
            row = UserRiskSetting(user_id=int(user_id), created_by=actor)
            self._session.add(row)
        for key, value in cleaned.items():
            setattr(row, key, value)
        row.updated_by = actor
        self._session.flush()
        return row

    def get_account_row(
        self, user_broker_account_id: int
    ) -> UserBrokerAccountRiskSetting | None:
        return self._session.scalar(
            select(UserBrokerAccountRiskSetting).where(
                UserBrokerAccountRiskSetting.user_broker_account_id
                == int(user_broker_account_id)
            )
        )

    def upsert_account(
        self,
        user_broker_account_id: int,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> UserBrokerAccountRiskSetting:
        cleaned = validate_risk_payload(payload, allow_null=True)
        row = self.get_account_row(user_broker_account_id)
        if row is None:
            row = UserBrokerAccountRiskSetting(
                user_broker_account_id=int(user_broker_account_id),
                created_by=actor,
            )
            self._session.add(row)
        for key, value in cleaned.items():
            setattr(row, key, value)
        row.updated_by = actor
        self._session.flush()
        return row

    def resolve(
        self,
        *,
        user_id: int | None = None,
        user_broker_account_id: int | None = None,
    ) -> ResolvedRiskPolicy:
        return self._resolver.resolve(
            user_id=user_id,
            user_broker_account_id=user_broker_account_id,
        )

    def snapshot_user(self, user_id: int) -> dict[str, Any]:
        return _snapshot_row(self.get_user_row(user_id))

    def snapshot_account(
        self, user_broker_account_id: int
    ) -> dict[str, Any]:
        return _snapshot_row(
            self.get_account_row(user_broker_account_id)
        )

    def snapshot_system(self) -> dict[str, Any]:
        return _snapshot_row(self.get_system())
