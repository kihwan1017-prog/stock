"""STEP 11-2 — OpenAI Compatible Provider (LM Studio / vLLM / 사내 API)."""

from __future__ import annotations

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
    timed_call,
    unsupported_response,
    usage_from_openai,
)
from stock_platform.ai.providers.http_client import (
    AIProviderHttpClient,
    ensure_success,
)
from stock_platform.common.settings import get_settings


class OpenAICompatibleProvider(AIProvider):
    provider_id = "openai_compatible"
    display_name = "OpenAI Compatible"

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
        return None

    async def shutdown(self) -> None:
        await self._http.aclose()

    def _allow_localhost(self) -> bool:
        return bool(
            getattr(
                get_settings(),
                "ai_provider_openai_compatible_allow_localhost",
                True,
            )
        )

    def _base_url(self) -> str:
        return validate_provider_endpoint(
            self._config.api_endpoint,
            allow_localhost=self._allow_localhost(),
            provider_id=self.provider_id,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._config.api_key.strip():
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        # custom headers — 제한적 (extra.headers dict)
        extra_headers = (self._config.extra or {}).get("headers")
        if isinstance(extra_headers, dict):
            for key, value in list(extra_headers.items())[:10]:
                key_s = str(key)
                if key_s.lower() in {
                    "authorization",
                    "cookie",
                    "host",
                    "content-length",
                }:
                    continue
                headers[key_s] = str(value)[:256]
        return headers

    def _ready(self) -> None:
        if not self._config.enabled:
            from stock_platform.ai.providers.errors import ProviderDisabledError

            raise ProviderDisabledError(self.provider_id)
        if not self._config.api_endpoint.strip():
            from stock_platform.ai.providers.errors import (
                ProviderNotConfiguredError,
            )

            raise ProviderNotConfiguredError(
                self.provider_id, "Endpoint not configured"
            )
        # endpoint 정책 즉시 검증
        self._base_url()

    async def health(self) -> ProviderHealth:
        caps = [c.value for c in self.capabilities()]
        local = local_config_health(
            self._config, require_api_key=False, capabilities=caps
        )
        if local is not None:
            return local
        try:
            self._base_url()
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
                version="openai-compatible",
                message="models OK",
                capabilities=caps,
            )
        except AIProviderError as exc:
            status = HealthStatus.ERROR
            if exc.code.startswith("INVALID_ENDPOINT") or exc.code.startswith(
                "ENDPOINT_"
            ):
                status = HealthStatus.ERROR
            elif exc.code == "TIMEOUT":
                status = HealthStatus.TIMEOUT
            elif exc.code == "HTTP_CONNECTION_ERROR":
                status = HealthStatus.OFFLINE
            elif exc.code == "AUTH_FAILED":
                status = HealthStatus.AUTH_FAILED
            return ProviderHealth(
                provider_id=self.provider_id,
                status=status,
                enabled=True,
                configured=bool(self._config.api_endpoint.strip()),
                model=self._config.model,
                endpoint_masked=mask_endpoint(self._config.api_endpoint),
                message=exc.message,
                capabilities=caps,
                sanitized_error_code=exc.code,
            )

    async def chat(self, request: AIChatRequest) -> AIResponse:
        model = request.model or self._config.model
        try:
            self._ready()
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
            return AIResponse(
                provider_id=self.provider_id,
                model=str(body.get("model") or model),
                content=str(message.get("content") or ""),
                finish_reason=map_finish_reason(choice.get("finish_reason")),
                usage=usage_from_openai(body.get("usage")),
                latency_ms=round(latency, 3),
                request_id=result.request_id or body.get("id"),
            )
        except AIProviderError as exc:
            return error_response(
                provider_id=self.provider_id, model=model, exc=exc
            )

    async def chat_stream(
        self, request: AIChatRequest
    ) -> AsyncIterator[StreamChunk]:
        response = await self.chat(request)
        yield StreamChunk(
            delta=response.content,
            done=True,
            finish_reason=response.finish_reason or FinishReason.STOP,
            usage=response.usage,
        )

    async def summarize(self, request: AIAnalyzeRequest) -> AIResponse:
        from stock_platform.ai.providers.dto import ChatMessage

        return await self.chat(
            AIChatRequest(
                messages=[
                    ChatMessage(role="system", content="Summarize briefly."),
                    ChatMessage(role="user", content=request.content),
                ],
                model=request.model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
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
