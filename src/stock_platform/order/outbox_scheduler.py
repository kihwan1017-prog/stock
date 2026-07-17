from __future__ import annotations

import asyncio
import logging

from stock_platform.order.outbox_worker import (
    OrderOutboxWorker,
)

logger = logging.getLogger(__name__)


class OrderOutboxScheduler:
    def __init__(
        self,
        *,
        worker: OrderOutboxWorker,
        interval_seconds: float = 1.0,
    ) -> None:
        self._worker = worker
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if (
            self._task is not None
            and not self._task.done()
        ):
            return

        self._stopping.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="order-outbox-worker",
        )

    async def shutdown(self) -> None:
        self._stopping.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                summary = await asyncio.to_thread(
                    self._worker.run_once
                )
                if summary.claimed:
                    logger.info(
                        "Order outbox processed: %s",
                        summary,
                    )
            except Exception:
                logger.exception(
                    "Order outbox worker failed"
                )

            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=self._interval,
                )
            except TimeoutError:
                pass
