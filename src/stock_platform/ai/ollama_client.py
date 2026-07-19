from __future__ import annotations

import json
from typing import Any

import httpx

from stock_platform.common.settings import Settings, get_settings


class OllamaError(RuntimeError):
    """Ollama 호출 또는 응답 처리 중 발생한 오류."""


class OllamaClient:
    """
    Ollama HTTP 클라이언트.

    지원 생성 방식:
    - OllamaClient(settings=get_settings())
    - OllamaClient(base_url=..., model=..., timeout_seconds=...)
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        *,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        resolved = settings or get_settings()
        self.base_url = (
            (base_url or resolved.ollama_base_url).rstrip("/")
        )
        self.model = model or resolved.ollama_model
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else resolved.ollama_timeout_seconds
        )
        self._temperature = resolved.ollama_temperature
        self._keep_alive = resolved.ollama_keep_alive
        self._http_client = http_client
        self._owns_client = http_client is None

    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self.timeout_seconds,
            )
        return self._http_client

    async def generate(
        self,
        *,
        prompt: str,
        model: str | None = None,
        format: str | dict[str, Any] | None = "json",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ollama /api/generate 원본 응답을 반환한다."""

        payload: dict[str, Any] = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self._keep_alive,
        }
        if format is not None:
            payload["format"] = format
        if options is not None:
            payload["options"] = options
        else:
            payload["options"] = {
                "temperature": self._temperature,
            }

        try:
            response = await self._client().post(
                f"{self.base_url}/api/generate",
                json=payload,
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
            body = response.json()
        except ValueError as exc:
            raise OllamaError(
                "Ollama HTTP 응답이 JSON 형식이 아닙니다."
            ) from exc

        if not isinstance(body, dict):
            raise OllamaError(
                "Ollama 응답이 객체 형식이 아닙니다."
            )
        return body

    async def generate_json(self, prompt: str) -> dict[str, Any]:
        """generate 후 response 필드를 JSON 객체로 파싱한다."""

        body = await self.generate(prompt=prompt, format="json")
        response_text = body.get("response", "")
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

    async def chat_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        system/user 프롬프트로 JSON 구조화 응답을 받는다.
        response_schema가 있으면 프롬프트에 스키마를 포함시킨다.
        """

        schema_hint = ""
        if response_schema:
            schema_hint = (
                "\n\n반드시 아래 JSON Schema 형태에 맞는 "
                "JSON 객체만 반환하세요.\n"
                + json.dumps(
                    response_schema,
                    ensure_ascii=False,
                    indent=2,
                )
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"{user_prompt}{schema_hint}",
            },
        ]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "keep_alive": self._keep_alive,
            "options": {"temperature": self._temperature},
        }

        try:
            response = await self._client().post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OllamaError(
                "Ollama 요청 시간이 초과되었습니다."
            ) from exc
        except httpx.HTTPStatusError as exc:
            # /api/chat 미지원 환경이면 generate로 폴백
            if exc.response.status_code in {404, 405}:
                combined = (
                    f"[SYSTEM]\n{system_prompt}\n\n"
                    f"[USER]\n{user_prompt}{schema_hint}"
                )
                return await self.generate_json(combined)
            raise OllamaError(
                "Ollama 서버가 오류를 반환했습니다. "
                f"status={exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise OllamaError(
                f"Ollama 서버 연결에 실패했습니다: {exc}"
            ) from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise OllamaError(
                "Ollama HTTP 응답이 JSON 형식이 아닙니다."
            ) from exc

        message = body.get("message") if isinstance(body, dict) else None
        content = ""
        if isinstance(message, dict):
            content = str(message.get("content") or "")
        elif isinstance(body, dict):
            content = str(body.get("response") or "")

        if not content.strip():
            raise OllamaError(
                "Ollama 응답 내용이 비어 있습니다."
            )

        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaError(
                "Ollama가 유효하지 않은 JSON을 반환했습니다."
            ) from exc

        if not isinstance(result, dict):
            raise OllamaError(
                "Ollama JSON 응답이 객체 형식이 아닙니다."
            )
        return result
