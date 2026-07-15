from __future__ import annotations

import asyncio
import os
from typing import Any

from stock_platform.broker.recovery_service import (
    BrokerRecoveryService,
)
from stock_platform.database.session import (
    get_session_factory,
)


class BrokerRecoveryManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._running = False
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    async def recover(self) -> dict[str, Any]:
        async with self._lock:
            if self._running:
                raise ValueError(
                    "Broker recovery is already running"
                )

            self._running = True
            self._last_error = None

            session = get_session_factory()()

            try:
                account_number = os.getenv(
                    "KIWOOM_ACCOUNT_NUMBER",
                    "",
                ).strip()

                if not account_number:
                    raise ValueError(
                        "KIWOOM_ACCOUNT_NUMBER is required"
                    )

                service = BrokerRecoveryService(
                    session=session,
                    account_number=account_number,
                    start_websocket=(
                        os.getenv(
                            "KIWOOM_RECOVERY_START_WS",
                            "true",
                        ).lower()
                        == "true"
                    ),
                    start_realtime_runners=(
                        os.getenv(
                            "KIWOOM_RECOVERY_START_TRADING",
                            "false",
                        ).lower()
                        == "true"
                    ),
                    start_scheduler=(
                        os.getenv(
                            "KIWOOM_RECOVERY_START_SCHEDULER",
                            "true",
                        ).lower()
                        == "true"
                    ),
                )

                result = await service.recover()

                self._last_result = {
                    "success": result.success,
                    "started_at": (
                        result.started_at.isoformat()
                    ),
                    "finished_at": (
                        result.finished_at.isoformat()
                    ),
                    "steps": [
                        {
                            "component": item.component.value,
                            "status": item.status.value,
                            "message": item.message,
                            "detail": item.detail,
                        }
                        for item in result.steps
                    ],
                }
                return self._last_result

            except Exception as exc:
                self._last_error = str(exc)
                raise
            finally:
                session.close()
                self._running = False

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "last_result": self._last_result,
            "last_error": self._last_error,
        }


broker_recovery_manager = BrokerRecoveryManager()
