"""Paper Outbox Worker / Fill Recovery lifecycle (Feature Flag, 기본 OFF)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from stock_platform.broker.paper.adapter import PaperBrokerAdapter
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher
from stock_platform.order.outbox_worker import OrderOutboxWorker

logger = logging.getLogger(__name__)


class PaperOutboxWorkerRuntime:
    """Paper 전용 Outbox Polling — LIVE Outbox와 claim 필터로 분리."""

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
        from datetime import timedelta

        settings = get_settings()
        batch = int(getattr(settings, "paper_outbox_worker_batch_size", 20))
        stale_sec = float(
            getattr(settings, "paper_outbox_worker_stale_seconds", 30.0)
        )
        return OrderOutboxWorker(
            session_factory=get_session_factory(),
            dispatcher=OrderOutboxDispatcher(PaperBrokerAdapter()),
            worker_id="paper-outbox-1",
            batch_size=max(1, batch),
            paper_only=True,
            stale_processing_after=timedelta(seconds=max(1.0, stale_sec)),
        )

    def start(self) -> dict[str, Any]:
        settings = get_settings()
        if not bool(getattr(settings, "paper_outbox_worker_enabled", False)):
            return {
                "started": False,
                "reason": "PAPER_OUTBOX_WORKER_DISABLED",
                **self.status(),
            }
        if self._task is not None and not self._task.done():
            return {
                "started": False,
                "reason": "ALREADY_RUNNING",
                **self.status(),
            }
        self._worker = self._build_worker()
        # 이벤트 루프가 바뀌면 Event를 새로 만든다 (pytest-asyncio)
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(),
            name="paper-outbox-worker",
        )
        self._started_at = datetime.now(timezone.utc)
        self._last_error = None
        self._consecutive_failures = 0
        return {"started": True, **self.status()}

    async def shutdown(self) -> None:
        """graceful stop 우선 — to_thread 중 cancel 시 DB 커넥션 orphan 방지."""

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
            getattr(settings, "paper_outbox_worker_interval_seconds", 1.0)
        )
        backoff = float(
            getattr(settings, "paper_outbox_worker_backoff_seconds", 2.0)
        )
        stopping = self._stopping
        if stopping is None:
            return
        try:
            while not stopping.is_set():
                try:
                    await self.run_once()
                    self._consecutive_failures = 0
                    self._last_error = None
                    sleep_for = max(0.2, interval)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._consecutive_failures += 1
                    self._last_error = type(exc).__name__
                    logger.exception("paper_outbox_worker_failed")
                    sleep_for = max(
                        interval,
                        backoff * min(self._consecutive_failures, 5),
                    )
                if stopping.is_set():
                    break
                try:
                    await asyncio.wait_for(
                        stopping.wait(),
                        timeout=sleep_for,
                    )
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        running = self._task is not None and not self._task.done()
        return {
            "enabled": bool(
                getattr(settings, "paper_outbox_worker_enabled", False)
            ),
            "running": running,
            "paper_only": True,
            "auto_fill_enabled": bool(
                getattr(settings, "paper_outbox_auto_fill", False)
            ),
            "interval_seconds": float(
                getattr(settings, "paper_outbox_worker_interval_seconds", 1.0)
            ),
            "batch_size": int(
                getattr(settings, "paper_outbox_worker_batch_size", 20)
            ),
            "started_at": (
                self._started_at.isoformat() if self._started_at else None
            ),
            "last_run_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "last_summary": self._last_summary,
            "last_error": self._last_error,
            "consecutive_failures": self._consecutive_failures,
        }


class PaperFillRecoveryScheduler:
    """ACCEPTED Paper 주문 주기 Recovery."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping: asyncio.Event | None = None
        self._last_run_at: datetime | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._run_count = 0

    def start(self) -> dict[str, Any]:
        settings = get_settings()
        if not bool(getattr(settings, "paper_fill_recovery_enabled", False)):
            return {
                "started": False,
                "reason": "PAPER_FILL_RECOVERY_DISABLED",
                **self.status(),
            }
        if self._task is not None and not self._task.done():
            return {
                "started": False,
                "reason": "ALREADY_RUNNING",
                **self.status(),
            }
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(),
            name="paper-fill-recovery",
        )
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
        self._stopping = None

    async def run_once(self) -> dict[str, Any]:
        from stock_platform.order.paper_fill_recovery import (
            recover_stalled_paper_accepted_orders,
        )

        settings = get_settings()
        limit = int(getattr(settings, "paper_fill_recovery_batch_size", 50))
        session = get_session_factory()()
        try:
            result = recover_stalled_paper_accepted_orders(
                session,
                limit=limit,
                actor="PAPER_FILL_RECOVERY_SCHEDULER",
            )
            self._last_run_at = datetime.now(timezone.utc)
            self._last_result = result
            self._run_count += 1
            self._last_error = None
            return result
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            self._last_error = type(exc).__name__
            logger.exception("paper_fill_recovery_failed")
            return {"filled": 0, "error": type(exc).__name__}
        finally:
            session.close()

    async def _run(self) -> None:
        settings = get_settings()
        interval = float(
            getattr(settings, "paper_fill_recovery_interval_seconds", 5.0)
        )
        stopping = self._stopping
        if stopping is None:
            return
        while not stopping.is_set():
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("paper_fill_recovery_loop_error")
            if stopping.is_set():
                break
            try:
                await asyncio.wait_for(
                    stopping.wait(),
                    timeout=max(1.0, interval),
                )
            except TimeoutError:
                pass

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        running = self._task is not None and not self._task.done()
        return {
            "enabled": bool(
                getattr(settings, "paper_fill_recovery_enabled", False)
            ),
            "running": running,
            "interval_seconds": float(
                getattr(settings, "paper_fill_recovery_interval_seconds", 5.0)
            ),
            "run_count": self._run_count,
            "last_run_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "last_result": self._last_result,
            "last_error": self._last_error,
        }


paper_outbox_worker_runtime = PaperOutboxWorkerRuntime()
paper_fill_recovery_scheduler = PaperFillRecoveryScheduler()
