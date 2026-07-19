"""Telegram Bot 운영 명령 핸들러."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.orm import Session

from stock_platform.notification.events import (
    NotificationEventType,
)
from stock_platform.notification.history import (
    NotificationSettings,
)
from stock_platform.notification.publisher import (
    notification_publisher,
)
from stock_platform.notification.telegram_status import (
    TelegramOpsStatusService,
)
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramCommandResult:
    ok: bool
    reply_text: str
    command: str
    authorized: bool
    detail: dict[str, Any]


class TelegramCommandHandler:
    """슬래시 명령을 처리한다. TelegramSender 직접 호출 없음."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._status = TelegramOpsStatusService(session)

    async def handle(
        self,
        *,
        chat_id: str,
        text: str,
        username: str | None = None,
    ) -> TelegramCommandResult:
        command = _extract_command(text)
        actor = f"TELEGRAM:{chat_id}"
        if username:
            actor = f"TELEGRAM:{username}:{chat_id}"

        self._audit(
            event_type="TELEGRAM_RECEIVE",
            actor=actor,
            detail={"chat_id": chat_id, "text": text[:200]},
        )

        if command is None:
            result = TelegramCommandResult(
                ok=False,
                reply_text="알 수 없는 명령입니다. /help",
                command="",
                authorized=True,
                detail={},
            )
            self._audit_command(actor, result)
            return result

        if not self._is_allowed_chat(chat_id):
            result = TelegramCommandResult(
                ok=False,
                reply_text="권한이 없습니다.",
                command=command,
                authorized=False,
                detail={"chat_id": chat_id},
            )
            self._audit(
                event_type="TELEGRAM_PERMISSION_DENIED",
                actor=actor,
                detail={
                    "command": command,
                    "chat_id": chat_id,
                },
            )
            self._audit_command(actor, result)
            return result

        try:
            reply = await self._dispatch_command(
                command=command,
                actor=actor,
            )
            result = TelegramCommandResult(
                ok=True,
                reply_text=reply,
                command=command,
                authorized=True,
                detail={},
            )
        except Exception as exc:
            logger.exception(
                "telegram_command_failed",
                command=command,
                error=str(exc),
            )
            result = TelegramCommandResult(
                ok=False,
                reply_text=f"명령 실패: {exc}",
                command=command,
                authorized=True,
                detail={"error": str(exc)},
            )

        self._audit_command(actor, result)
        return result

    async def _dispatch_command(
        self,
        *,
        command: str,
        actor: str,
    ) -> str:
        if command == "/help":
            return self._status.build_help_text()
        if command == "/status":
            return await self._status.build_status_text()
        if command == "/system":
            return self._status.build_system_text()
        if command == "/health":
            return await self._status.build_health_text()
        if command == "/orders":
            return self._status.build_orders_text()
        if command == "/positions":
            return self._status.build_positions_text()
        if command == "/kill":
            return await self._activate_kill(actor=actor)
        if command == "/resume":
            return await self._deactivate_kill(actor=actor)
        return "지원하지 않는 명령입니다. /help"

    async def _activate_kill(self, *, actor: str) -> str:
        state = KillSwitchService(self._session).activate(
            actor=actor,
            reason="Telegram /kill command",
        )
        self._session.commit()
        await notification_publisher.publish_async(
            event_type=NotificationEventType.KILL_SWITCH,
            title="Kill Switch Activated",
            message=f"Activated by {actor}",
            detail={"status": state.status.value},
        )
        return (
            f"<b>🛑 Kill Switch ACTIVE</b>\n"
            f"by {actor}\n"
            f"status={state.status.value}"
        )

    async def _deactivate_kill(self, *, actor: str) -> str:
        state = KillSwitchService(self._session).deactivate(
            actor=actor,
            reason="Telegram /resume command",
        )
        self._session.commit()
        await notification_publisher.publish_async(
            event_type=NotificationEventType.KILL_SWITCH,
            title="Kill Switch Deactivated",
            message=f"Deactivated by {actor}",
            detail={"status": state.status.value},
        )
        return (
            f"<b>✅ Kill Switch OFF</b>\n"
            f"by {actor}\n"
            f"status={state.status.value}"
        )

    @staticmethod
    def _is_allowed_chat(chat_id: str) -> bool:
        settings = NotificationSettings.from_env()
        allowed = set(settings.allowed_chat_ids)
        if not allowed:
            # chat_id 미설정 시 운영 명령 거부 (안전)
            return False
        return str(chat_id).strip() in allowed

    def _audit_command(
        self,
        actor: str,
        result: TelegramCommandResult,
    ) -> None:
        self._audit(
            event_type="TELEGRAM_COMMAND",
            actor=actor,
            detail={
                "command": result.command,
                "ok": result.ok,
                "authorized": result.authorized,
                **result.detail,
            },
        )

    def _audit(
        self,
        *,
        event_type: str,
        actor: str,
        detail: dict[str, Any],
    ) -> None:
        try:
            from stock_platform.api.deps_admin import (
                AuditLogService,
            )

            AuditLogService(self._session).record(
                event_type=event_type,
                actor=actor,
                detail=detail,
            )
            self._session.commit()
        except Exception as exc:
            self._session.rollback()
            logger.warning(
                "telegram_audit_failed",
                error=str(exc),
            )


def _extract_command(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None
    token = raw.split()[0]
    # /status@BotName → /status
    command = token.split("@", 1)[0].lower()
    known = {
        "/status",
        "/system",
        "/health",
        "/orders",
        "/positions",
        "/kill",
        "/resume",
        "/help",
    }
    if command in known:
        return command
    return None
