from __future__ import annotations

import os
from decimal import Decimal

from stock_platform.database.session import (
    get_session_factory,
)
from stock_platform.risk_engine.daily_loss_monitor import (
    DailyLossMonitor,
)
from stock_platform.risk_engine.runtime import (
    realtime_risk_policy,
)


class DailyLossMonitorManager:
    def __init__(self) -> None:
        self._last_snapshot = None
        self._last_error: str | None = None

    async def check_now(self):
        account_number = os.getenv(
            "KIWOOM_ACCOUNT_NUMBER",
            "",
        ).strip()

        if not account_number:
            raise ValueError(
                "KIWOOM_ACCOUNT_NUMBER is required"
            )

        session = get_session_factory()()

        try:
            snapshot = await DailyLossMonitor(
                session=session,
                loss_limit=(
                    realtime_risk_policy.max_daily_loss
                ),
            ).check(
                broker_code="KIWOOM",
                account_number=account_number,
            )
            self._last_snapshot = snapshot
            self._last_error = None
            return snapshot
        except Exception as exc:
            session.rollback()
            self._last_error = str(exc)
            raise
        finally:
            session.close()

    def status(self):
        return {
            "last_snapshot": self._last_snapshot,
            "last_error": self._last_error,
            "loss_limit": str(
                realtime_risk_policy.max_daily_loss
            ),
        }


daily_loss_monitor_manager = DailyLossMonitorManager()
