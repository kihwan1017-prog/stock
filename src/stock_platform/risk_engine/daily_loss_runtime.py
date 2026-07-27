from __future__ import annotations

import structlog
from sqlalchemy import select

from stock_platform.database.session import get_session_factory
from stock_platform.risk_engine.daily_loss_monitor import DailyLossMonitor
from stock_platform.risk_engine.runtime import realtime_risk_policy
from stock_platform.trading.account_models import (
    PaperAccount,
    UserBrokerAccount,
)

logger = structlog.get_logger(__name__)


class DailyLossMonitorManager:
    """STEP 8-5-19 — 활성 UBA + Paper Account 전수 Daily Loss."""

    def __init__(self) -> None:
        self._last_snapshots: list = []
        self._last_error: str | None = None
        self._missing_logged = False

    async def check_now(self):
        session = get_session_factory()()
        try:
            uba_ids = list(
                session.scalars(
                    select(UserBrokerAccount.user_broker_account_id).where(
                        UserBrokerAccount.is_active.is_(True)
                    )
                )
            )
            paper_ids = list(
                session.scalars(
                    select(PaperAccount.account_id).where(
                        PaperAccount.is_active.is_(True)
                    )
                )
            )
            if not uba_ids and not paper_ids:
                message = "no active UBA or paper accounts"
                self._last_error = message
                if not self._missing_logged:
                    logger.info(
                        "daily_loss_monitor_skipped",
                        reason=message,
                    )
                    self._missing_logged = True
                self._last_snapshots = []
                return None

            monitor = DailyLossMonitor(
                session=session,
                loss_limit=realtime_risk_policy.max_daily_loss,
            )
            results = []
            for uba_id in uba_ids:
                try:
                    snap = await monitor.check_uba(
                        user_broker_account_id=int(uba_id),
                    )
                    results.append(snap)
                except LookupError as exc:
                    logger.info(
                        "daily_loss_monitor_uba_skipped",
                        user_broker_account_id=int(uba_id),
                        reason=str(exc),
                    )
            for paper_id in paper_ids:
                try:
                    snap = await monitor.check_paper(
                        paper_account_id=int(paper_id),
                    )
                    results.append(snap)
                except LookupError as exc:
                    logger.info(
                        "daily_loss_monitor_paper_skipped",
                        paper_account_id=int(paper_id),
                        reason=str(exc),
                    )
            session.commit()
            self._last_snapshots = results
            self._last_error = None
            self._missing_logged = False
            return results[-1] if results else None
        except Exception as exc:
            session.rollback()
            self._last_error = str(exc)
            raise
        finally:
            session.close()

    def status(self):
        return {
            "last_snapshot": (
                self._last_snapshots[-1] if self._last_snapshots else None
            ),
            "checked_uba_count": sum(
                1
                for s in self._last_snapshots
                if getattr(s, "user_broker_account_id", None) is not None
            ),
            "checked_paper_count": sum(
                1
                for s in self._last_snapshots
                if getattr(s, "paper_account_id", None) is not None
            ),
            "last_error": self._last_error,
            "loss_limit": str(realtime_risk_policy.max_daily_loss),
            "identity_mode": "uba_and_paper_account",
        }


daily_loss_monitor_manager = DailyLossMonitorManager()
