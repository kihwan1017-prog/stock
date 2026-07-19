"""Telegram Ops long-polling 스케줄러."""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.notification.telegram_bot_client import (
    TelegramBotClient,
)
from stock_platform.notification.telegram_commands import (
    TelegramCommandHandler,
)


logger = structlog.get_logger(__name__)


class TelegramOpsPoller:
    def __init__(self) -> None:
        self._offset: int | None = None
        self._last_error: str | None = None

    async def poll_once(self) -> int:
        settings = get_settings()
        if not settings.telegram_ops_enabled:
            return 0
        if not settings.telegram_bot_token.strip():
            return 0

        client = TelegramBotClient()
        updates = await client.get_updates(
            offset=self._offset,
            timeout=0,
        )
        handled = 0
        for update in updates:
            update_id = int(update.get("update_id", 0))
            self._offset = update_id + 1
            message = update.get("message") or {}
            text = message.get("text") or ""
            chat = message.get("chat") or {}
            chat_id = str(chat.get("id") or "")
            if not chat_id or not text.startswith("/"):
                continue

            from_user = message.get("from") or {}
            username = from_user.get("username")
            session = get_session_factory()()
            try:
                result = await TelegramCommandHandler(
                    session
                ).handle(
                    chat_id=chat_id,
                    text=text,
                    username=username,
                )
                session.commit()
                await client.send_html(
                    chat_id=chat_id,
                    text=result.reply_text,
                )
                handled += 1
            except Exception as exc:
                session.rollback()
                self._last_error = str(exc)
                logger.exception(
                    "telegram_ops_poll_item_failed",
                    error=str(exc),
                )
            finally:
                session.close()

        self._last_error = None
        return handled

    def status(self) -> dict:
        settings = get_settings()
        return {
            "enabled": settings.telegram_ops_enabled,
            "offset": self._offset,
            "last_error": self._last_error,
        }


telegram_ops_poller = TelegramOpsPoller()


class TelegramOpsScheduler:
    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )

    def configure(self) -> None:
        settings = get_settings()
        interval = max(
            1.0,
            float(
                getattr(
                    settings,
                    "telegram_ops_poll_interval_seconds",
                    3.0,
                )
            ),
        )
        self._scheduler.add_job(
            telegram_ops_poller.poll_once,
            trigger=IntervalTrigger(seconds=interval),
            id="telegram_ops_poller",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(int(interval), 5),
        )

    def start(self) -> None:
        settings = get_settings()
        if not settings.telegram_ops_enabled:
            logger.info(
                "telegram_ops_poller_skipped",
                reason="disabled_by_settings",
            )
            return
        if self._scheduler.running:
            return
        self.configure()
        self._scheduler.start()
        logger.info(
            "telegram_ops_poller_started",
            interval_seconds=getattr(
                settings,
                "telegram_ops_poll_interval_seconds",
                3.0,
            ),
        )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("telegram_ops_poller_stopped")


telegram_ops_scheduler = TelegramOpsScheduler()
