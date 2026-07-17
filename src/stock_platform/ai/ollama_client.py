from __future__ import annotations

import json
from typing import Any

import httpx


class OllamaError(RuntimeError):
    """Ollama 호출 또는 응답 처리 중 발생한 오류."""


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate_json(
        self,
        prompt: str,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )

                response.raise_for_status()

        except httpx.TimeoutException as exc:
            raise OllamaError(
                "Ollama 요청 시간이 초과되었습니다."
            ) from exc

        except httpx.HTTPStatusError as exc:
            raise OllamaError(
                "Ollama 서버가 오류를 반환했습니다. "
                f"status={exc.response.status_code}"
            ) from exc

        except httpx.RequestError as exc:
            raise OllamaError(
                f"Ollama 서버 연결에 실패했습니다: {exc}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise OllamaError(
                "Ollama HTTP 응답이 JSON 형식이 아닙니다."
            ) from exc

        response_text = payload.get(
            "response",
            "",
        )

        if not isinstance(response_text, str):
            raise OllamaError(
                "Ollama response 필드가 문자열이 아닙니다."
            )

        if not response_text.strip():
            raise OllamaError(
                "Ollama 응답 내용이 비어 있습니다."
            )

        try:
            result = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise OllamaError(
                "Ollama가 유효하지 않은 JSON을 반환했습니다."
            ) from exc

        if not isinstance(result, dict):
            raise OllamaError(
                "Ollama JSON 응답이 객체 형식이 아닙니다."
            )

        return result
