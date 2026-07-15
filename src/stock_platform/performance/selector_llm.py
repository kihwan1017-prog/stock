from __future__ import annotations

import json
from typing import Any

import httpx


class OllamaStrategySelectorClient:
    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        timeout_seconds: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._client = client

    @property
    def model_name(self) -> str:
        return self._model_name

    async def select(
        self,
        *,
        prompt: str,
    ) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout_seconds
        )

        try:
            response = await client.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model_name,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if owns_client:
                await client.aclose()

        raw = payload.get("response")

        if isinstance(raw, dict):
            return raw

        if not isinstance(raw, str) or not raw.strip():
            raise RuntimeError(
                "Ollama strategy selector returned an empty response"
            )

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Ollama strategy selector returned invalid JSON"
            ) from exc
