"""STEP 11-2 — OpenAI Provider (Official Chat Completions HTTP API)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from stock_platform.ai.providers.base import AIProvider
from stock_platform.ai.providers.capability import AICapability
from stock_platform.ai.providers.config import AIProviderConfig
from stock_platform.ai.providers.dto import (
    AIAnalyzeRequest,
    AIChatRequest,
    AIEmbeddingRequest,
    AIEmbeddingResponse,
    AIResponse,
    FinishReason,
    ProviderHealth,
    StreamChunk,
    TokenUsage,
)
from stock_platform.ai.providers.endpoint_policy import (
    mask_endpoint,
    validate_provider_endpoint,
)
from stock_platform.ai.providers.errors import AIProviderError
from stock_platform.ai.providers.health_status import HealthStatus
from stock_platform.ai.providers.helpers import (
    error_response,
    local_config_health,
    map_finish_reason,
    require_ready,
    timed_call,
    unsupported_response,
    usage_from_openai,
)
from stock_platform.ai.providers.http_client import (
    AIProviderHttpClient,
    ensure_success,
)


class OpenAIProvider(AIProvider):
    provider_id = "openai"
    display_name = "OpenAI"

    def __init__(
        self,
        config: AIProviderConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self.provider_id = config.provider_id
        self._http = AIProviderHttpClient(
            provider_id=self.provider_id,
            timeout_seconds=config.timeout_seconds,
            http_client=http_client,
        )
        self._initialized = False

    def capabilities(self) -> frozenset[AICapability]:
        return frozenset(
            {
                AICapability.CHAT,
                AICapability.JSON,
                AICapability.STREAM,
                AICapability.SUMMARIZE,
            }
        )

    async def initialize(self) -> None:
        self._initialized = True

    async def shutdown(self) -> None:
        await self._http.aclose()
        self._initialized = False

    def _base_url(self) -> str:
        return validate_provider_endpoint(
            self._config.api_endpoint or "https://api.openai.com/v1",
            allow_localhost=False,
            provider_id=self.provider_id,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }

    async def health(self) -> ProviderHealth:
        caps = [c.value for c in self.capabilities()]
        local = local_config_health(
            self._config,
            require_api_key=True,
            capabilities=caps,
        )
        if local is not None:
            return local
        # 저비용: models 목록 조회
        try:
            result, latency = await timed_call(
                self._http.request(
                    "GET",
                    f"{self._base_url()}/models",
                    headers=self._headers(),
                )
            )
            ensure_success(result, provider_id=self.provider_id)
            return ProviderHealth(
                provider_id=self.provider_id,
                status=HealthStatus.HEALTHY,
                enabled=True,
                configured=True,
                latency_ms=round(latency, 3),
                model=self._config.model,
                endpoint_masked=mask_endpoint(self._base_url()),
                version="openai-v1",
                message="models list OK",
                capabilities=caps,
            )
        except AIProviderError as exc:
            status = HealthStatus.ERROR
            if exc.code == "AUTH_FAILED":
                status = HealthStatus.AUTH_FAILED
            elif exc.code == "RATE_LIMITED":
                status = HealthStatus.RATE_LIMITED
            elif exc.code == "TIMEOUT":
                status = HealthStatus.TIMEOUT
            elif exc.code == "HTTP_CONNECTION_ERROR":
                status = HealthStatus.OFFLINE
            return ProviderHealth(
                provider_id=self.provider_id,
                status=status,
                enabled=True,
                configured=True,
                model=self._config.model,
                endpoint_masked=mask_endpoint(self._config.api_endpoint),
                message=exc.message,
                capabilities=caps,
                sanitized_error_code=exc.code,
            )

    async def chat(self, request: AIChatRequest) -> AIResponse:
        model = request.model or self._config.model
        try:
            require_ready(self._config, require_api_key=True)
            payload: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": m.role, "content": m.content}
                    for m in request.messages
                ],
                "temperature": (
                    request.temperature
                    if request.temperature is not None
                    else self._config.temperature
                ),
                "max_tokens": (
                    request.max_tokens
                    if request.max_tokens is not None
                    else self._config.max_tokens
                ),
            }
            if request.json_mode:
                payload["response_format"] = {"type": "json_object"}

            result, latency = await timed_call(
                self._http.request(
                    "POST",
                    f"{self._base_url()}/chat/completions",
                    headers=self._headers(),
                    json_body=payload,
                )
            )
            ensure_success(result, provider_id=self.provider_id)
            body = result.json_body if isinstance(result.json_body, dict) else {}
            choices = body.get("choices") or []
            choice = choices[0] if choices else {}
            message = choice.get("message") or {}
            content = str(message.get("content") or "")
            return AIResponse(
                provider_id=self.provider_id,
                model=str(body.get("model") or model),
                content=content,
                finish_reason=map_finish_reason(choice.get("finish_reason")),
                usage=usage_from_openai(body.get("usage")),
                latency_ms=round(latency, 3),
                request_id=result.request_id or body.get("id"),
                raw={"id": body.get("id")},
            )
        except AIProviderError as exc:
            return error_response(
                provider_id=self.provider_id,
                model=model,
                exc=exc,
            )

    async def chat_stream(
        self, request: AIChatRequest
    ) -> AsyncIterator[StreamChunk]:
        model = request.model or self._config.model
        require_ready(self._config, require_api_key=True)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in request.messages
            ],
            "stream": True,
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self._config.temperature
            ),
            "max_tokens": (
                request.max_tokens
                if request.max_tokens is not None
                else self._config.max_tokens
            ),
        }
        async for line in self._http.stream_lines(
            "POST",
            f"{self._base_url()}/chat/completions",
            headers=self._headers(),
            json_body=payload,
        ):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                yield StreamChunk(delta="", done=True, finish_reason=FinishReason.STOP)
                return
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            delta = ((obj.get("choices") or [{}])[0].get("delta") or {}).get(
                "content"
            ) or ""
            if delta:
                yield StreamChunk(delta=delta, done=False)

    async def summarize(self, request: AIAnalyzeRequest) -> AIResponse:
        from stock_platform.ai.providers.dto import ChatMessage

        return await self.chat(
            AIChatRequest(
                messages=[
                    ChatMessage(role="system", content="Summarize briefly."),
                    ChatMessage(role="user", content=request.content),
                ],
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
        )

    async def analyze_news(self, request: AIAnalyzeRequest) -> AIResponse:
        return unsupported_response(
            provider_id=self.provider_id,
            model=request.model or self._config.model,
            capability="NEWS",
        )

    async def analyze_chart(self, request: AIAnalyzeRequest) -> AIResponse:
        return unsupported_response(
            provider_id=self.provider_id,
            model=request.model or self._config.model,
            capability="CHART",
        )

    async def generate_strategy(self, request: AIAnalyzeRequest) -> AIResponse:
        return unsupported_response(
            provider_id=self.provider_id,
            model=request.model or self._config.model,
            capability="STRATEGY",
        )

    async def embedding(
        self, request: AIEmbeddingRequest
    ) -> AIEmbeddingResponse:
        return AIEmbeddingResponse(
            provider_id=self.provider_id,
            model=request.model or self._config.model,
            vectors=[],
            error=unsupported_response(
                provider_id=self.provider_id,
                model=request.model or self._config.model,
                capability="EMBEDDING",
            ).error,
        )
