"""STEP 8-8 — Broker Disconnect → LIVE OFF / Scheduler Pause."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.live_safety_audit import (
    BROKER_DISCONNECTED,
    BROKER_RECOVERED,
    emit_live_order_telegram,
    emit_live_safety_audit,
)
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_arm_service import LiveArmService


class BrokerDisconnectProtector:
    """Broker Down 시 자동 LIVE OFF. 복구 후 자동 LIVE ON 금지."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def on_broker_down(
        self,
        *,
        broker_code: str,
        actor: str = "BROKER_MONITOR",
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        broker = broker_code.strip().upper()
        rows = list(
            self._session.scalars(
                select(UserBrokerAccount).where(
                    UserBrokerAccount.broker_code == broker,
                    UserBrokerAccount.live_order_enabled.is_(True),
                )
            )
        )
        arm = LiveArmService(self._session)
        disabled: list[int] = []
        for uba in rows:
            arm.disarm(
                int(uba.user_broker_account_id),
                actor=actor,
                reason="BROKER_DISCONNECTED",
                turn_live_off=True,
            )
            disabled.append(int(uba.user_broker_account_id))

        payload = {
            "broker_code": broker,
            "disabled_accounts": disabled,
            **(detail or {}),
        }
        emit_live_safety_audit(
            self._session,
            event_type=BROKER_DISCONNECTED,
            actor=actor,
            run_id=None,
            user_id=None,
            account_id=None,
            strategy_id=None,
            detail=payload,
            commit=False,
        )
        emit_live_order_telegram(
            event_type=BROKER_DISCONNECTED,
            title="Broker Down",
            message=f"{broker} disconnected — LIVE OFF / ARM cleared",
            detail=payload,
        )
        self._pause_runtimes(actor=actor, reason="BROKER_DISCONNECTED")
        return payload

    def on_broker_up(
        self,
        *,
        broker_code: str,
        actor: str = "BROKER_MONITOR",
    ) -> dict[str, Any]:
        """복구 알림만 — 자동 LIVE ON / ARM 금지."""

        payload = {
            "broker_code": broker_code.upper(),
            "auto_live_on": False,
            "requires_admin_arm": True,
        }
        emit_live_safety_audit(
            self._session,
            event_type=BROKER_RECOVERED,
            actor=actor,
            run_id=None,
            user_id=None,
            account_id=None,
            strategy_id=None,
            detail=payload,
            commit=False,
        )
        emit_live_order_telegram(
            event_type=BROKER_RECOVERED,
            title="Broker Up",
            message=(
                f"{broker_code.upper()} recovered — "
                "Admin ARM required before LIVE orders"
            ),
            detail=payload,
        )
        return payload

    def _pause_runtimes(self, *, actor: str, reason: str) -> None:
        try:
            import asyncio

            from stock_platform.strategy_deployment.runtime_manager import (
                dynamic_strategy_runtime_manager,
            )

            coro = dynamic_strategy_runtime_manager.pause_all(reason=reason)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(coro)
            except RuntimeError:
                asyncio.run(coro)
        except Exception:  # noqa: BLE001
            pass
        emit_live_order_telegram(
            event_type="SCHEDULER_PAUSE",
            title="Scheduler Pause",
            message=f"Pause after {reason}",
            detail={"reason": reason, "actor": actor},
        )
