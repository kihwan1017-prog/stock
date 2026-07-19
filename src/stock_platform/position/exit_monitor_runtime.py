"""Position Exit Monitor 런타임 — 주기적 폴링 실행 본체."""

from __future__ import annotations

import structlog

from stock_platform.common.settings import get_settings
from stock_platform.database.session import (
    get_session_factory,
)
from stock_platform.position.exit_monitor import (
    PositionExitAction,
    PositionExitMonitorService,
)
from stock_platform.position.exit_monitor_loader import (
    PositionExitMonitorLoader,
)


logger = structlog.get_logger(__name__)


class PositionExitMonitorManager:
    def __init__(self) -> None:
        self._last_actions: list[PositionExitAction] = []
        self._last_error: str | None = None
        self._scan_count = 0

    async def check_now(
        self,
    ) -> list[PositionExitAction] | None:
        settings = get_settings()
        if not settings.position_exit_monitor_enabled:
            return None

        session = get_session_factory()()
        try:
            context = PositionExitMonitorLoader(
                session
            ).load()
            if context.skipped_symbols:
                logger.info(
                    "position_exit_positions_skipped",
                    symbols=context.skipped_symbols,
                )

            monitor = PositionExitMonitorService(session)
            # 시스템 청산은 계정번호 미설정 환경에서도 동작
            actions = monitor.evaluate_and_exit(
                context.positions,
                skip_risk_checks=True,
            )
            session.commit()
            self._last_actions = actions
            self._last_error = None
            self._scan_count += 1
            return actions
        except Exception as exc:
            session.rollback()
            self._last_error = str(exc)
            logger.exception(
                "position_exit_monitor_tick_failed",
                error=str(exc),
            )
            raise
        finally:
            session.close()

    def status(self) -> dict:
        settings = get_settings()
        return {
            "enabled": (
                settings.position_exit_monitor_enabled
            ),
            "interval_seconds": (
                settings.position_exit_monitor_interval_seconds
            ),
            "scan_count": self._scan_count,
            "last_error": self._last_error,
            "last_exit_count": sum(
                1
                for item in self._last_actions
                if item.submitted
            ),
            "last_actions": [
                {
                    "symbol": item.symbol,
                    "reason": item.reason,
                    "submitted": item.submitted,
                    "order_id": item.order_id,
                }
                for item in self._last_actions
            ],
        }


position_exit_monitor_manager = (
    PositionExitMonitorManager()
)
