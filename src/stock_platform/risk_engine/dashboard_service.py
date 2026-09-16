from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.ws_manager import (
    kiwoom_order_websocket_manager,
)
from stock_platform.notification.runtime import (
    risk_notification_sender,
)
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_strategy_runner,
)
from stock_platform.risk_engine.daily_loss_runtime import (
    daily_loss_monitor_manager,
)
from stock_platform.risk_engine.dashboard_models import (
    RiskDashboardPositionSummary,
    RiskDashboardSnapshot,
)
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)
from stock_platform.risk_engine.risk_event_entities import (
    RiskEventEntity,
)
from stock_platform.risk_engine.risk_event_repository import (
    RiskEventRepository,
)
from stock_platform.risk_engine.runtime import (
    realtime_risk_policy,
)


ZERO = Decimal("0")


class RiskDashboardService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def build(
        self,
        *,
        user_broker_account_id: int | None = None,
        recent_limit: int = 50,
    ) -> RiskDashboardSnapshot:
        if recent_limit < 1 or recent_limit > 200:
            raise ValueError(
                "recent_limit must be between 1 and 200"
            )

        kill_switch = KillSwitchService(
            self._session
        ).get_state()

        position = None
        masked_ref = None
        if user_broker_account_id is not None:
            position = self._position_summary_by_uba(
                user_broker_account_id=int(user_broker_account_id)
            )
            masked_ref = f"UBA:{int(user_broker_account_id)}"

        daily_loss_status = (
            daily_loss_monitor_manager.status()
        )
        daily_loss = self._daily_loss_summary(
            daily_loss_status
        )

        recent_events = [
            {
                "risk_event_id": item.risk_event_id,
                "event_type": item.event_type,
                "event_level": item.event_level,
                "broker_code": item.broker_code,
                "user_broker_account_id": item.user_broker_account_id,
                "paper_account_id": item.paper_account_id,
                "masked_account_ref": item.masked_account_ref,
                "correlation_id": item.correlation_id,
                "current_loss_amount": str(
                    item.current_loss_amount
                ),
                "loss_limit_amount": str(
                    item.loss_limit_amount
                ),
                "message": item.message,
                "detail_payload": item.detail_payload,
                "created_at": item.created_at,
            }
            for item in RiskEventRepository(
                self._session
            ).recent(limit=recent_limit)
        ]

        blocked_event_count = self._session.scalar(
            select(func.count())
            .select_from(RiskEventEntity)
            .where(
                RiskEventEntity.event_level.in_(
                    ["WARNING", "CRITICAL"]
                )
            )
        ) or 0

        execution_status = (
            realtime_execution_runner.status()
        )
        strategy_status = (
            realtime_strategy_runner.status()
        )

        return RiskDashboardSnapshot(
            generated_at=datetime.now(timezone.utc),
            user_broker_account_id=user_broker_account_id,
            masked_account_ref=masked_ref,
            kill_switch={
                "status": kill_switch.status.value,
                "reason": kill_switch.reason,
                "activated_by": (
                    kill_switch.activated_by
                ),
                "activated_at": (
                    kill_switch.activated_at
                ),
                "deactivated_by": (
                    kill_switch.deactivated_by
                ),
                "deactivated_at": (
                    kill_switch.deactivated_at
                ),
            },
            daily_loss=daily_loss,
            broker={
                "order_websocket": (
                    kiwoom_order_websocket_manager
                    .status()
                ),
                "account_snapshot_found": (
                    position is not None
                ),
            },
            notification=(
                risk_notification_sender.status()
            ),
            risk_engine={
                "max_order_amount": str(
                    realtime_risk_policy
                    .max_order_amount
                ),
                "max_order_quantity": str(
                    realtime_risk_policy
                    .max_order_quantity
                ),
                "max_open_positions": (
                    realtime_risk_policy
                    .max_open_positions
                ),
                "max_investment_ratio": str(
                    realtime_risk_policy
                    .max_investment_ratio
                ),
                "max_daily_loss": str(
                    realtime_risk_policy
                    .max_daily_loss
                ),
                "warning_or_critical_event_count": (
                    int(blocked_event_count)
                ),
            },
            execution={
                "execution_runner": execution_status,
                "strategy_runner": strategy_status,
            },
            position=position,
            recent_events=recent_events,
        )

    def _position_summary_by_uba(
        self,
        *,
        user_broker_account_id: int,
    ) -> RiskDashboardPositionSummary | None:
        from stock_platform.broker.account_repository import (
            BrokerAccountSnapshotRepository,
        )
        from stock_platform.broker.snapshot_constants import (
            BrokerSnapshotStatus,
        )

        account, positions = BrokerAccountSnapshotRepository(
            self._session
        ).get_active_by_uba(int(user_broker_account_id))
        if account is None:
            return None
        positions = [
            item
            for item in positions
            if Decimal(item.quantity) > 0
            and item.snapshot_status
            == BrokerSnapshotStatus.ACTIVE.value
        ]
        invested_amount = sum(
            (
                Decimal(item.evaluation_amount)
                for item in positions
            ),
            ZERO,
        )
        cash_balance = Decimal(
            account.available_order_amount
        )
        total_asset_value = (
            cash_balance + invested_amount
        )
        investment_ratio = (
            invested_amount / total_asset_value
            if total_asset_value > ZERO
            else ZERO
        )

        return RiskDashboardPositionSummary(
            cash_balance=cash_balance,
            invested_amount=invested_amount,
            total_asset_value=total_asset_value,
            investment_ratio=investment_ratio,
            open_position_count=len(positions),
        )

    @staticmethod
    def _daily_loss_summary(
        status: dict,
    ) -> dict:
        snapshot = status.get("last_snapshot")

        if snapshot is None:
            return {
                "status": "NOT_CHECKED",
                "current_loss_amount": "0",
                "loss_limit_amount": status.get(
                    "loss_limit",
                    "0",
                ),
                "progress_ratio": "0",
                "checked_at": None,
                "last_error": status.get(
                    "last_error"
                ),
            }

        limit_amount = Decimal(
            snapshot.loss_limit_amount
        )
        current_loss = Decimal(
            snapshot.current_loss_amount
        )
        progress_ratio = (
            current_loss / limit_amount
            if limit_amount > ZERO
            else ZERO
        )

        return {
            "status": snapshot.status.value,
            "realized_profit_loss": str(
                snapshot.realized_profit_loss
            ),
            "unrealized_profit_loss": str(
                snapshot.unrealized_profit_loss
            ),
            "combined_profit_loss": str(
                snapshot.combined_profit_loss
            ),
            "current_loss_amount": str(
                current_loss
            ),
            "loss_limit_amount": str(
                limit_amount
            ),
            "progress_ratio": str(
                progress_ratio
            ),
            "kill_switch_activated": (
                snapshot.kill_switch_activated
            ),
            "checked_at": snapshot.checked_at,
            "last_error": status.get(
                "last_error"
            ),
        }
