"""STEP 8-8 — LIVE 운영 보호 Dashboard 집계."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_arm_service import LiveArmService

KST = ZoneInfo("Asia/Seoul")
OPEN_STATUSES = (
    "CREATED",
    "PENDING",
    "SENT",
    "ACCEPTED",
    "PARTIALLY_FILLED",
    "CANCEL_REQUESTED",
    "REPLACE_REQUESTED",
)


class LiveOpsDashboardService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        now_kst = datetime.now(KST)
        day_start = datetime(
            now_kst.year, now_kst.month, now_kst.day, tzinfo=KST
        ).astimezone(timezone.utc)

        accounts = list(self._session.scalars(select(UserBrokerAccount)))
        arm = LiveArmService(self._session)
        live_on = 0
        armed = 0
        account_rows: list[dict[str, Any]] = []
        for uba in accounts:
            arm.expire_if_needed(int(uba.user_broker_account_id))
            status = arm.get_arm_status(int(uba.user_broker_account_id))
            if status["live_order_enabled"]:
                live_on += 1
            if status["live_armed"]:
                armed += 1
            account_rows.append(status)

        open_orders = int(
            self._session.scalar(
                select(func.count())
                .select_from(TradingOrderEntity)
                .where(TradingOrderEntity.status_code.in_(OPEN_STATUSES))
            )
            or 0
        )
        today_orders = int(
            self._session.scalar(
                select(func.count())
                .select_from(TradingOrderEntity)
                .where(TradingOrderEntity.created_at >= day_start)
            )
            or 0
        )
        pending = int(
            self._session.scalar(
                select(func.count())
                .select_from(TradingOrderEntity)
                .where(TradingOrderEntity.status_code == "PENDING")
            )
            or 0
        )

        from stock_platform.risk_engine.kill_switch_models import (
            KillSwitchStatus,
        )

        kill = KillSwitchService(self._session).get_state()
        kill_payload = {
            "active": kill.status == KillSwitchStatus.ACTIVE,
            "status": str(kill.status),
            "reason": kill.reason,
            "activated_by": kill.activated_by,
            "activated_at": (
                kill.activated_at.isoformat()
                if kill.activated_at
                else None
            ),
        }

        scheduler = self._scheduler_status()
        broker = self._broker_status()
        daily_loss = self._daily_loss_summary()
        post_fill = self._post_fill_summary()

        return {
            "generated_at": now.isoformat(),
            "live": {
                "accounts_live_on": live_on,
                "accounts_armed": armed,
                "accounts": account_rows,
            },
            "kill_switch": kill_payload,
            "broker": broker,
            "scheduler": scheduler,
            "orders": {
                "pending": pending,
                "open_orders": open_orders,
                "today_orders": today_orders,
            },
            "daily_loss": daily_loss,
            "post_fill_verification": post_fill,
        }

    def _scheduler_status(self) -> dict[str, Any]:
        try:
            from stock_platform.common.settings import get_settings

            settings = get_settings()
            return {
                "scheduler_enabled": bool(
                    getattr(settings, "scheduler_enabled", False)
                ),
                "lifecycle_scheduler_enabled": bool(
                    getattr(settings, "lifecycle_scheduler_enabled", False)
                ),
            }
        except Exception:  # noqa: BLE001
            return {"scheduler_enabled": None}

    def _broker_status(self) -> dict[str, Any]:
        try:
            from stock_platform.operation.live_health_gate import (
                evaluate_live_order_health,
            )

            health = evaluate_live_order_health(self._session)
            return {
                "live_order_allowed": bool(health.get("allowed", False)),
                "status": health.get("status") or health.get("level"),
                "detail": {
                    k: health[k]
                    for k in health
                    if k not in {"allowed"}
                },
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "live_order_allowed": False,
                "status": "UNKNOWN",
                "error": type(exc).__name__,
            }

    def _post_fill_summary(self) -> dict[str, Any]:
        try:
            from stock_platform.order.post_fill_verification_service import (
                PostFillVerificationService,
            )

            return PostFillVerificationService(self._session).dashboard_counts()
        except Exception as exc:  # noqa: BLE001
            return {
                "pending": 0,
                "waiting_snapshot": 0,
                "mismatch": 0,
                "expired": 0,
                "failed": 0,
                "error": type(exc).__name__,
            }

    def _daily_loss_summary(self) -> dict[str, Any]:
        try:
            from stock_platform.risk_engine.daily_loss_entities import (
                AccountDailyLossEntity,
            )

            today = datetime.now(KST).date()
            rows = list(
                self._session.scalars(
                    select(AccountDailyLossEntity).where(
                        AccountDailyLossEntity.trading_date == today
                    )
                )
            )
            breached = [
                int(r.user_broker_account_id)
                for r in rows
                if r.user_broker_account_id is not None
                and str(r.status_code).upper()
                in {"BREACHED", "LIMIT_REACHED", "KILL"}
            ]
            return {
                "trading_date": today.isoformat(),
                "accounts_tracked": len(rows),
                "breached_uba_ids": breached,
            }
        except Exception:  # noqa: BLE001
            return {"accounts_tracked": 0, "breached_uba_ids": []}
