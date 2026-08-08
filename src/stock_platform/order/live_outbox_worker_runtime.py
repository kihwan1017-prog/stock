"""LIVE Outbox Worker lifecycle — Paper worker와 claim 분리 (기본 OFF)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher
from stock_platform.order.outbox_worker import OrderOutboxWorker

logger = logging.getLogger(__name__)


class LiveOutboxWorkerRuntime:
    """LIVE environment Outbox만 claim — paper_only worker와 혼입 방지.

    기본 OFF(Fail Closed). 켜져도 OutboxWorker가 UBA LIVE/ARM·Activation
    등 기존 LIVE gate를 dispatch 시점에 강제한다.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping: asyncio.Event | None = None
        self._worker: OrderOutboxWorker | None = None
        self._last_error: str | None = None
        self._last_run_at: datetime | None = None
        self._last_summary: dict[str, Any] | None = None
        self._started_at: datetime | None = None
        self._consecutive_failures = 0

    def _build_worker(self) -> OrderOutboxWorker:
        settings = get_settings()
        batch = int(getattr(settings, "live_outbox_worker_batch_size", 20))
        stale_sec = float(
            getattr(settings, "live_outbox_worker_stale_seconds", 30.0)
        )
        return OrderOutboxWorker(
            session_factory=get_session_factory(),
            # 고정 Paper adapter 금지 — payload로 Upbit/Kiwoom resolve
            dispatcher=OrderOutboxDispatcher(adapter=None),
            worker_id="live-outbox-1",
            batch_size=max(1, batch),
            paper_only=False,
            live_only=True,
            stale_processing_after=timedelta(seconds=max(1.0, stale_sec)),
        )

    def start(self) -> dict[str, Any]:
        settings = get_settings()
        if not bool(getattr(settings, "live_outbox_worker_enabled", False)):
            return {
                "started": False,
                "reason": "LIVE_OUTBOX_WORKER_DISABLED",
                **self.status(),
            }
        if self._task is not None and not self._task.done():
            return {
                "started": False,
                "reason": "ALREADY_RUNNING",
                **self.status(),
            }
        self._worker = self._build_worker()
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(),
            name="live-outbox-worker",
        )
        self._started_at = datetime.now(timezone.utc)
        self._last_error = None
        self._consecutive_failures = 0
        return {"started": True, **self.status()}

    async def shutdown(self) -> None:
        if self._stopping is not None:
            self._stopping.set()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=6.0)
            except TimeoutError:
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except (
                    asyncio.CancelledError,
                    TimeoutError,
                    Exception,
                ):  # noqa: BLE001
                    pass
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._started_at = None
        self._stopping = None

    async def run_once(self) -> dict[str, Any]:
        if self._worker is None:
            self._worker = self._build_worker()
        summary = await asyncio.to_thread(self._worker.run_once)
        payload = {
            "claimed": summary.claimed,
            "succeeded": summary.succeeded,
            "retried": summary.retried,
            "failed": summary.failed,
            "ambiguous": summary.ambiguous,
        }
        self._last_run_at = datetime.now(timezone.utc)
        self._last_summary = payload
        return payload

    async def _run(self) -> None:
        settings = get_settings()
        interval = float(
            getattr(settings, "live_outbox_worker_interval_seconds", 1.0)
        )
        backoff = float(
            getattr(settings, "live_outbox_worker_backoff_seconds", 2.0)
        )
        while self._stopping is not None and not self._stopping.is_set():
            try:
                await self.run_once()
                self._consecutive_failures = 0
                self._last_error = None
                wait = max(0.2, interval)
            except Exception as exc:  # noqa: BLE001
                self._consecutive_failures += 1
                self._last_error = f"{type(exc).__name__}:{exc}"[:300]
                logger.exception("live_outbox_worker_tick_failed")
                wait = max(interval, backoff * self._consecutive_failures)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=wait)
            except TimeoutError:
                continue

    def status(self) -> dict[str, Any]:
        running = self._task is not None and not self._task.done()
        return {
            "enabled": bool(
                getattr(get_settings(), "live_outbox_worker_enabled", False)
            ),
            "running": running,
            "started_at": (
                self._started_at.isoformat() if self._started_at else None
            ),
            "last_run_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "last_summary": self._last_summary,
            "last_error": self._last_error,
            "consecutive_failures": self._consecutive_failures,
            "worker_id": "live-outbox-1",
            "live_only": True,
        }


live_outbox_worker_runtime = LiveOutboxWorkerRuntime()
