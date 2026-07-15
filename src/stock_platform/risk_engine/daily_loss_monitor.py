from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.account_models import (
    BrokerAccountSnapshotEntity,
    BrokerPositionSnapshotEntity,
)
from stock_platform.risk_engine.alert import (
    LoggingRiskAlertNotifier,
    RiskAlertNotifier,
)
from stock_platform.risk_engine.daily_loss_models import (
    DailyLossMonitorStatus,
    DailyLossSnapshot,
)
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)
from stock_platform.risk_engine.risk_event_repository import (
    RiskEventRepository,
)


ZERO = Decimal("0")


class DailyLossMonitor:
    def __init__(
        self,
        *,
        session: Session,
        loss_limit: Decimal,
        notifier: RiskAlertNotifier | None = None,
    ) -> None:
        if loss_limit <= ZERO:
            raise ValueError(
                "loss_limit must be greater than zero"
            )

        self._session = session
        self._loss_limit = loss_limit
        self._notifier = (
            notifier or LoggingRiskAlertNotifier()
        )
        self._kill_switch = KillSwitchService(session)
        self._events = RiskEventRepository(session)

    async def check(
        self,
        *,
        broker_code: str,
        account_number: str,
    ) -> DailyLossSnapshot:
        account = self._session.scalar(
            select(BrokerAccountSnapshotEntity).where(
                BrokerAccountSnapshotEntity.broker_code
                == broker_code.upper(),
                BrokerAccountSnapshotEntity.account_number
                == account_number,
            )
        )

        if account is None:
            raise LookupError(
                "Broker account snapshot not found"
            )

        positions = list(
            self._session.scalars(
                select(BrokerPositionSnapshotEntity).where(
                    BrokerPositionSnapshotEntity.broker_code
                    == broker_code.upper(),
                    BrokerPositionSnapshotEntity.account_number
                    == account_number,
                    BrokerPositionSnapshotEntity.quantity > 0,
                )
            )
        )

        realized = Decimal(
            account.total_profit_loss
        )
        unrealized = sum(
            (
                Decimal(item.profit_loss)
                for item in positions
            ),
            ZERO,
        )
        combined = realized + unrealized
        current_loss = max(-combined, ZERO)

        kill_switch_was_active = (
            self._kill_switch.is_active()
        )
        activated = False

        if current_loss >= self._loss_limit:
            status = (
                DailyLossMonitorStatus.KILL_SWITCH_ACTIVE
                if kill_switch_was_active
                else DailyLossMonitorStatus.LIMIT_REACHED
            )

            if not kill_switch_was_active:
                reason = (
                    "Daily loss limit reached: "
                    f"{current_loss} >= {self._loss_limit}"
                )
                self._kill_switch.activate(
                    actor="SYSTEM_DAILY_LOSS_MONITOR",
                    reason=reason,
                )
                activated = True

                detail = {
                    "broker_code": broker_code.upper(),
                    "account_number": account_number,
                    "realized_profit_loss": str(realized),
                    "unrealized_profit_loss": str(
                        unrealized
                    ),
                    "combined_profit_loss": str(combined),
                    "current_loss_amount": str(
                        current_loss
                    ),
                    "loss_limit_amount": str(
                        self._loss_limit
                    ),
                }

                self._events.create(
                    event_type="AUTO_KILL_SWITCH",
                    event_level="CRITICAL",
                    broker_code=broker_code.upper(),
                    account_number=account_number,
                    current_loss_amount=current_loss,
                    loss_limit_amount=self._loss_limit,
                    message=reason,
                    detail_payload=detail,
                )

                await self._notifier.send(
                    title="자동매매 긴급정지",
                    message=reason,
                    detail=detail,
                )
        else:
            status = DailyLossMonitorStatus.SAFE

        return DailyLossSnapshot(
            broker_code=broker_code.upper(),
            account_number=account_number,
            realized_profit_loss=realized,
            unrealized_profit_loss=unrealized,
            combined_profit_loss=combined,
            current_loss_amount=current_loss,
            loss_limit_amount=self._loss_limit,
            status=status,
            kill_switch_activated=activated,
            checked_at=datetime.now(timezone.utc),
        )

    def reset_daily_state(
        self,
        *,
        actor: str,
        reason: str,
    ) -> dict:
        state = self._kill_switch.get_state()

        return {
            "reset": True,
            "kill_switch_status": state.status.value,
            "message": (
                "Daily monitor has no independent loss "
                "counter. Account snapshots are the source."
            ),
            "actor": actor,
            "reason": reason,
        }
