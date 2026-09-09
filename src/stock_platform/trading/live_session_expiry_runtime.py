"""ARM/Activation 만료 주기 스캔 — 주문/Runtime 기동 없음.

기존 LiveOutboxWorkerRuntime 패턴(asyncio loop + Event)을 재사용한다.
새 스케줄러 프레임워크를 도입하지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory

logger = logging.getLogger(__name__)


class LiveSessionExpiryRuntime:
    """expire_all_due + Activation cascade를 짧게 반복한다."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping: asyncio.Event | None = None
        self._last_error: str | None = None
        self._last_run_at: datetime | None = None
        self._last_summary: dict[str, Any] | None = None
        self._started_at: datetime | None = None
        self._consecutive_failures = 0
        self._running = False

    def start(self) -> dict[str, Any]:
        if self._task is not None and not self._task.done():
            return {
                "started": False,
                "reason": "ALREADY_RUNNING",
                **self.status(),
            }
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(),
            name="live-session-expiry",
        )
        self._started_at = datetime.now(timezone.utc)
        self._last_error = None
        self._consecutive_failures = 0
        self._running = True
        return {"started": True, **self.status()}

    async def shutdown(self) -> None:
        if self._stopping is not None:
            self._stopping.set()
        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=8.0)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._task = None
        self._stopping = None
        self._running = False

    def run_once(self) -> dict[str, Any]:
        """동기 1회 스캔 — 테스트/startup에서 사용."""

        from stock_platform.trading.live_session_expiry import (
            scan_and_expire_live_sessions,
        )

        factory = get_session_factory()
        session = factory()
        try:
            summary = scan_and_expire_live_sessions(
                session, actor="SYSTEM"
            )
            session.commit()
            return summary
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def _run(self) -> None:
        settings = get_settings()
        interval = float(
            getattr(
                settings,
                "live_session_expiry_scan_interval_seconds",
                15.0,
            )
        )
        interval = max(5.0, min(60.0, interval))
        # 기동 직후 stale LIVE/ARM 1회 회수
        try:
            summary = await asyncio.to_thread(self.run_once)
            self._last_run_at = datetime.now(timezone.utc)
            self._last_summary = summary
            self._last_error = None
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"{type(exc).__name__}:{exc}"[:300]
            logger.exception("live_session_expiry_startup_scan_failed")

        while self._stopping is not None and not self._stopping.is_set():
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=interval
                )
                break
            except TimeoutError:
                pass
            if self._stopping is None or self._stopping.is_set():
                break
            try:
                summary = await asyncio.to_thread(self.run_once)
                self._last_run_at = datetime.now(timezone.utc)
                self._last_summary = summary
                self._consecutive_failures = 0
                self._last_error = None
            except Exception as exc:  # noqa: BLE001
                self._consecutive_failures += 1
                self._last_error = f"{type(exc).__name__}:{exc}"[:300]
                logger.exception("live_session_expiry_tick_failed")

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        running = self._task is not None and not self._task.done()
        return {
            "running": running,
            "interval_seconds": float(
                getattr(
                    settings,
                    "live_session_expiry_scan_interval_seconds",
                    15.0,
                )
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
            "note": (
                "Activation/ARM 만료 스캔만 수행. "
                "주문·Runtime·Outbox worker 기동 없음"
            ),
        }


live_session_expiry_runtime = LiveSessionExpiryRuntime()
