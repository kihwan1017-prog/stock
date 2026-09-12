"""STEP 8-5-21 — LIVE Dry Run (Broker API 미호출)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.broker.live_config_gate import (
    evaluate_live_flag_consistency,
)
from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)
from stock_platform.common.settings import get_settings
from stock_platform.operation.live_health_gate import (
    evaluate_live_order_health,
)


@dataclass
class LiveDryRunResult:
    allowed: bool
    blocked_by: list[str] = field(default_factory=list)
    order_amount: str = "0"
    quantity: str = "0"
    price: str | None = None
    risk: dict[str, Any] = field(default_factory=dict)
    activation_gate: dict[str, Any] = field(default_factory=dict)
    config_gate: dict[str, Any] = field(default_factory=dict)
    health: dict[str, Any] = field(default_factory=dict)
    broker_endpoint_called: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiveOrderDryRunService:
    """주문 흐름을 Broker 직전에서 중단하는 Dry Run."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def run(
        self,
        *,
        user_id: int,
        user_broker_account_id: int,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal | None,
        broker_code: str = "KIWOOM",
    ) -> LiveDryRunResult:
        settings = get_settings()
        qty = Decimal(str(quantity))
        px = Decimal(str(price)) if price is not None else None
        amount = (qty * px) if px is not None else Decimal("0")
        blocked: list[str] = []

        config = evaluate_live_flag_consistency(
            broker_code=broker_code,
            session=self._session,
            user_broker_account_id=user_broker_account_id,
        )
        if config.code in {
            "LIVE_MOCK_CONFLICT",
            "LIVE_FLAG_MISMATCH_KIWOOM",
            "GLOBAL_LIVE_OFF",
            "UPBIT_LIVE_OFF",
            "UPBIT_MOCK_LIVE_CONFLICT",
        }:
            blocked.append(config.code)

        health = evaluate_live_order_health(self._session)
        if not health.get("live_orders_allowed"):
            blocked.append("SYSTEM_HEALTH_CRITICAL")

        activation = LiveTradingTransitionService(
            self._session
        ).get_active()
        activation_payload: dict[str, Any]
        if activation is None:
            blocked.append("ACTIVATION_MISSING_OR_EXPIRED")
            activation_payload = {"active": False}
        else:
            activation_payload = {
                "active": True,
                "expires_at": (
                    activation.expires_at.isoformat()
                    if activation.expires_at
                    else None
                ),
                "approved_by": activation.approved_by,
                "max_order_amount": str(activation.max_order_amount),
                "broker_code": activation.broker_code,
                "user_broker_account_id": activation.user_broker_account_id,
            }
            if (
                activation.user_broker_account_id is not None
                and int(activation.user_broker_account_id)
                != int(user_broker_account_id)
            ):
                blocked.append("ACTIVATION_UBA_SCOPE_MISMATCH")
            if str(activation.broker_code).upper() != broker_code.upper():
                blocked.append("ACTIVATION_BROKER_MISMATCH")
            if amount > Decimal(str(activation.max_order_amount)):
                blocked.append("ACTIVATION_MAX_ORDER_EXCEEDED")

        # 소액 LIVE 한도 (설정 기반)
        max_order = Decimal(str(settings.live_small_max_order_amount))
        if px is None:
            blocked.append("MARKET_ORDER_REQUIRES_PRICE_ESTIMATE")
        elif amount > max_order:
            blocked.append("LIVE_SMALL_MAX_ORDER_AMOUNT")
        if amount <= 0:
            blocked.append("INVALID_ORDER_AMOUNT")

        # Kill Switch — 조회만
        try:
            from stock_platform.risk_engine.kill_switch_guard import (
                PersistentKillSwitchGuard,
            )

            PersistentKillSwitchGuard(
                self._session
            ).require_order_allowed(
                side=side.upper(),
                allow_sell=True,
                exchange_code="KRX",
                user_broker_account_id=user_broker_account_id,
            )
        except Exception as exc:  # noqa: BLE001
            blocked.append(f"KILL_SWITCH:{type(exc).__name__}")

        risk_payload = {
            "evaluated": True,
            "user_id": user_id,
            "user_broker_account_id": user_broker_account_id,
            "symbol": symbol,
            "side": side.upper(),
        }

        return LiveDryRunResult(
            allowed=len(blocked) == 0,
            blocked_by=blocked,
            order_amount=str(amount),
            quantity=str(qty),
            price=None if px is None else str(px),
            risk=risk_payload,
            activation_gate=activation_payload,
            config_gate={
                "code": config.code,
                "status": config.status,
                "message": config.message,
                "detail": config.detail,
            },
            health=health,
            broker_endpoint_called=False,
            detail={"broker_code": broker_code.upper()},
        )
