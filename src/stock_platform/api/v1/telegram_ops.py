"""Telegram Ops API — webhook · 명령 테스트 · 상태."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session
from stock_platform.notification.history import (
    NotificationSettings,
)
from stock_platform.notification.runtime import (
    notification_service,
)
from stock_platform.notification.telegram_bot_client import (
    TelegramBotClient,
)
from stock_platform.notification.telegram_commands import (
    TelegramCommandHandler,
)
from stock_platform.notification.telegram_polling import (
    telegram_ops_poller,
)


router = APIRouter(
    prefix="/api/v1/telegram",
    tags=["Telegram Ops"],
)


class TelegramWebhookUpdate(BaseModel):
    update_id: int | None = None
    message: dict[str, Any] | None = None


class TelegramCommandTestRequest(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=500)
    username: str | None = Field(
        default=None,
        max_length=100,
    )
    send_reply: bool = False


@router.get("/ops/status")
def get_telegram_ops_status(
    _: str = Depends(require_admin),
):
    return {
        "settings": NotificationSettings.from_env().to_dict(),
        "poller": telegram_ops_poller.status(),
        "notification_service": notification_service.status(),
    }


@router.post("/webhook")
async def telegram_webhook(
    update: TelegramWebhookUpdate,
    request: Request,
    session: Session = Depends(get_db_session),
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None,
        alias="X-Telegram-Bot-Api-Secret-Token",
    ),
):
    """Telegram이 Push하는 Update를 수신한다."""

    enforce_rate_limit(
        request,
        scope="telegram_webhook",
        limit=120,
        window_seconds=60,
    )
    expected = get_settings().telegram_webhook_secret.strip()
    if expected:
        import secrets

        provided = (x_telegram_bot_api_secret_token or "").strip()
        if not provided or not secrets.compare_digest(
            provided, expected
        ):
            return {"ok": False, "handled": False, "error": "forbidden"}

    message = update.message or {}
    text = message.get("text") or ""
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    if not chat_id or not text.startswith("/"):
        return {"ok": True, "handled": False}

    from_user = message.get("from") or {}
    result = await TelegramCommandHandler(session).handle(
        chat_id=chat_id,
        text=text,
        username=from_user.get("username"),
    )
    session.commit()

    try:
        await TelegramBotClient().send_html(
            chat_id=chat_id,
            text=result.reply_text,
        )
    except Exception:
        return {
            "ok": False,
            "handled": True,
            "command": result.command,
        }

    return {
        "ok": result.ok,
        "handled": True,
        "command": result.command,
        "authorized": result.authorized,
    }


@router.post("/commands/test")
async def test_telegram_command(
    request: TelegramCommandTestRequest,
    _: str = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """Admin이 로컬에서 명령을 시뮬레이션한다."""

    result = await TelegramCommandHandler(session).handle(
        chat_id=request.chat_id,
        text=request.text,
        username=request.username,
    )
    session.commit()

    if request.send_reply and result.authorized:
        await TelegramBotClient().send_html(
            chat_id=request.chat_id,
            text=result.reply_text,
        )

    audit.record(
        event_type="TELEGRAM_COMMAND_TEST",
        actor="ADMIN_API",
        detail={
            "chat_id": request.chat_id,
            "text": request.text,
            "ok": result.ok,
            "authorized": result.authorized,
            "command": result.command,
        },
    )
    session.commit()

    return {
        "ok": result.ok,
        "authorized": result.authorized,
        "command": result.command,
        "reply_text": result.reply_text,
        "detail": result.detail,
    }
