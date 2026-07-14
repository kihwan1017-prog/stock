from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

import structlog

from stock_platform.database.session import (
    get_session_factory,
)
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
)
from stock_platform.realtime.order_executor import (
    RealtimePaperOrderExecutor,
)
from stock_platform.realtime.signal_bus import (
    RealtimeSignalBus,
)


logger = structlog.get_logger(__name__)


class RealtimeExecutionRunner:
    """실시간 신호 버스를 구독해 모의 주문을 실행한다."""

    def __init__(
        self,
        *,
        signal_bus: RealtimeSignalBus,
        config: RealtimeExecutionConfig,
        history_size: int = 500,
    ) -> None:
        self._signal_bus = signal_bus
        self._config = config
        self._task: asyncio.Task | None = None
        self._running = False
        self._processed_count = 0
        self._executed_count = 0
        self._failed_count = 0
        self._last_error: str | None = None
        self._history: deque[dict[str, Any]] = deque(
            maxlen=history_size
        )

    async def start(self) -> dict:
        if self._task is not None:
            raise ValueError(
                "Realtime execution runner is already running"
            )

        self._task = asyncio.create_task(
            self.run_forever(),
            name="realtime-execution-runner",
        )
        return self.status()

    async def run_forever(self) -> None:
        self._running = True

        try:
            async for signal in self._signal_bus.subscribe():
                self._processed_count += 1
                session = get_session_factory()()

                try:
                    result = RealtimePaperOrderExecutor(
                        session=session,
                        config=self._config,
                    ).execute(signal)

                    if result.order_status != "SKIPPED":
                        self._executed_count += 1

                    self._history.appendleft(
                        self._to_dict(result)
                    )
                    self._last_error = None

                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    session.rollback()
                    self._failed_count += 1
                    self._last_error = str(exc)
                    logger.exception(
                        "realtime_execution_failed",
                        exchange_code=(
                            signal.exchange_code
                        ),
                        symbol=signal.symbol,
                        action=signal.action.value,
                    )
                finally:
                    session.close()
        finally:
            self._running = False

    async def stop(self) -> None:
        if self._task is None:
            return

        self._task.cancel()

        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    def status(self) -> dict:
        return {
            "running": self._running,
            "mode": self._config.mode.value,
            "account_id": self._config.account_id,
            "order_amount": str(
                self._config.order_amount
            ),
            "auto_fill": self._config.auto_fill,
            "allow_buy": self._config.allow_buy,
            "allow_sell": self._config.allow_sell,
            "processed_count": self._processed_count,
            "executed_count": self._executed_count,
            "failed_count": self._failed_count,
            "last_error": self._last_error,
        }

    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    @staticmethod
    def _to_dict(result) -> dict[str, Any]:
        return {
            "exchange_code": result.exchange_code,
            "symbol": result.symbol,
            "signal_action": result.signal_action,
            "execution_mode": result.execution_mode,
            "order_id": result.order_id,
            "trade_id": result.trade_id,
            "order_status": result.order_status,
            "quantity": str(result.quantity),
            "order_price": str(result.order_price),
            "reason_code": result.reason_code,
            "executed_at": (
                result.executed_at.isoformat()
            ),
        }
