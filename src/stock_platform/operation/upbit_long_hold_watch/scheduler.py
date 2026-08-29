# -*- coding: utf-8 -*-
"""Long-hold watch scheduler — observability only."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory

logger = logging.getLogger(__name__)

_LOADED = False


class UpbitLongHoldWatchScheduler:
    """주기적으로 AUTO 장기보유 Alert V2 발행 (SELL 없음)."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping: asyncio.Event | None = None
        self._last_run_at: datetime | None = None
        self._last_summary: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._running = False

    def start(self) -> dict[str, Any]:
        global _LOADED
        if self._task is not None and not self._task.done():
            _LOADED = True
            return {"started": False, "reason": "ALREADY_RUNNING", **self.status()}
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(), name="upbit-long-hold-watch"
        )
        self._running = True
        _LOADED = True
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

    async def run_once(self) -> dict[str, Any]:
        from stock_platform.operation.upbit_long_hold_watch.service import (
            run_long_hold_watch_once,
        )

        settings = get_settings()
        uba = int(
            getattr(settings, "mobile_default_upbit_uba_id", None) or 1380
        )
        session = get_session_factory()()
        try:
            summary = run_long_hold_watch_once(
                session, user_broker_account_id=uba, emit=True
            )
            # delivery-only — commit 불필요 (notification publisher가 자체 세션 사용)
            self._last_run_at = datetime.now(timezone.utc)
            self._last_summary = {
                "long_hold_count": summary.get("long_hold_count"),
                "results": summary.get("results"),
                "sell_created": 0,
            }
            self._last_error = None
            return summary
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"{type(exc).__name__}:{exc}"[:300]
            logger.exception("long_hold_watch_tick_failed")
            return {"error": self._last_error, "sell_created": 0}
        finally:
            session.close()

    async def _run(self) -> None:
        settings = get_settings()
        interval = float(
            getattr(settings, "upbit_long_hold_watch_interval_seconds", 60.0)
            or 60.0
        )
        interval = max(30.0, min(600.0, interval))
        try:
            await self.run_once()
        except Exception:  # noqa: BLE001
            logger.exception("long_hold_watch_startup_tick_failed")
        while self._stopping is not None and not self._stopping.is_set():
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)
                break
            except TimeoutError:
                pass
            if self._stopping is None or self._stopping.is_set():
                break
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("long_hold_watch_tick_failed")

    def status(self) -> dict[str, Any]:
        alive = self._task is not None and not self._task.done()
        return {
            "loaded": True,
            "running": self._running and alive,
            "task_alive": alive,
            "last_run_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "last_error": self._last_error,
            "last_summary": self._last_summary,
            "max_holding_time_real": None,
            "real_time_exit_enabled": False,
        }


def long_hold_watch_loaded() -> bool:
    return bool(_LOADED)


upbit_long_hold_watch_scheduler = UpbitLongHoldWatchScheduler()
