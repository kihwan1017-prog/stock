from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from stock_platform.common.settings import Settings, get_settings


logger = structlog.get_logger(__name__)


class OllamaError(RuntimeError):
    """Base exception for Ollama API failures."""


class OllamaResponseError(OllamaError):
    """Raised when Ollama returns invalid structured output."""


class OllamaClient:
    """Small async client for Ollama /api/chat."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._owns_http_client = http_client is None

    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def chat_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        client = await self._get_http_client()
        url = (
            f"{self._settings.ollama_base_url.rstrip('/')}"
            "/api/chat"
        )

        payload = {
            "model": self._settings.ollama_model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "format": response_schema,
            "stream": False,
            "think": False,
            "keep_alive": self._settings.ollama_keep_alive,
            "options": {
                "temperature": self._settings.ollama_temperature,
            },
        }

        try:
            response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Ollama request failed: {exc.__class__.__name__}"
            ) from exc

        if response.is_error:
            raise OllamaError(
                f"Ollama request failed: HTTP "
                f"{response.status_code}"
            )

        try:
            body = response.json()
            content = body["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise OllamaResponseError(
                "Ollama chat response did not contain message.content"
            ) from exc

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaResponseError(
                "Ollama structured response was not valid JSON"
            ) from exc

        if not isinstance(parsed, dict):
            raise OllamaResponseError(
                "Ollama structured response must be an object"
            )

        logger.info(
            "ollama_structured_chat_completed",
            model=self._settings.ollama_model,
            total_duration=body.get("total_duration"),
            eval_count=body.get("eval_count"),
        )

        return parsed

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self._settings.ollama_timeout_seconds
                )
            )

        return self._http_client
