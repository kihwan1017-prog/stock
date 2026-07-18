from __future__ import annotations

import structlog

from stock_platform.common.settings import get_settings
from stock_platform.database.session import (
    get_session_factory,
)
from stock_platform.risk_engine.daily_loss_monitor import (
    DailyLossMonitor,
)
from stock_platform.risk_engine.runtime import (
    realtime_risk_policy,
)

logger = structlog.get_logger(__name__)


class DailyLossMonitorManager:
    def __init__(self) -> None:
        self._last_snapshot = None
        self._last_error: str | None = None
        self._missing_logged = False

    async def check_now(self):
        account_number = get_settings().kiwoom_account_number.strip()

        if not account_number:
            # 계좌번호 미설정은 운영 전 단계 — 예외 대신 skip
            message = "KIWOOM_ACCOUNT_NUMBER is not set"
            self._last_error = message
            if not self._missing_logged:
                logger.info(
                    "daily_loss_monitor_skipped",
                    reason=message,
                )
                self._missing_logged = True
            return None

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
            self._missing_logged = False
            return snapshot
        except LookupError as exc:
            # 스냅샷 동기화 전이면 정상 skip (traceback 스팸 방지)
            session.rollback()
            self._last_error = str(exc)
            if not self._missing_logged:
                logger.info(
                    "daily_loss_monitor_skipped",
                    reason=str(exc),
                )
                self._missing_logged = True
            return None
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
