"""Telegram Bot API 클라이언트 — Ops polling/webhook 전용 전송.

도메인 Service는 이 모듈을 직접 쓰지 않는다.
알림 이벤트는 NotificationPublisher → NotificationService 경로를 사용한다.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from stock_platform.common.settings import get_settings


logger = structlog.get_logger(__name__)


class TelegramBotClient:
    def __init__(
        self,
        *,
        bot_token: str | None = None,
        timeout_seconds: float = 25.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._bot_token = (
            bot_token or settings.telegram_bot_token
        ).strip()
        self._timeout_seconds = timeout_seconds
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._bot_token)

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 0,
    ) -> list[dict[str, Any]]:
        if not self._bot_token:
            return []
        params: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            params["offset"] = offset

        payload = await self._post("getUpdates", params)
        if not payload.get("ok"):
            raise RuntimeError(
                str(payload.get("description", "getUpdates failed"))
            )
        return list(payload.get("result") or [])

    async def send_html(
        self,
        *,
        chat_id: str,
        text: str,
    ) -> dict[str, Any]:
        if not self._bot_token:
            raise RuntimeError("Telegram bot token is missing")
        payload = await self._post(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        logger.info(
            "telegram_reply_sent",
            chat_id=chat_id,
            ok=bool(payload.get("ok")),
        )
        return payload

    async def _post(
        self,
        method: str,
        json_body: dict[str, Any],
    ) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout_seconds
        )
        try:
            response = await client.post(
                (
                    "https://api.telegram.org/bot"
                    f"{self._bot_token}/{method}"
                ),
                json=json_body,
            )
            response.raise_for_status()
            return response.json()
        finally:
            if owns_client:
                await client.aclose()
