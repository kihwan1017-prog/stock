"""STEP 11-2 — Google Gemini Provider (Generative Language API)."""

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
    TokenUsage,
)
from stock_platform.ai.providers.endpoint_policy import (
    mask_endpoint,
    validate_provider_endpoint,
)
from stock_platform.ai.providers.errors import (
    AIProviderError,
    ProviderSafetyBlockedError,
)
from stock_platform.ai.providers.health_status import HealthStatus
from stock_platform.ai.providers.helpers import (
    error_response,
    local_config_health,
    map_finish_reason,
    require_ready,
    timed_call,
    unsupported_response,
)
from stock_platform.ai.providers.http_client import (
    AIProviderHttpClient,
    ensure_success,
)


class GeminiProvider(AIProvider):
    provider_id = "gemini"
    display_name = "Gemini"

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

    def _base_url(self) -> str:
        return validate_provider_endpoint(
            self._config.api_endpoint
            or "https://generativelanguage.googleapis.com",
            allow_localhost=False,
            provider_id=self.provider_id,
        )

    def _model_path(self, model: str) -> str:
        name = model if model.startswith("models/") else f"models/{model}"
        return f"{self._base_url()}/v1beta/{name}"

    def _to_contents(
        self, request: AIChatRequest
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for msg in request.messages:
            if msg.role == "system":
                system_parts.append(msg.content)
                continue
            role = "model" if msg.role == "assistant" else "user"
            contents.append(
                {"role": role, "parts": [{"text": msg.content}]}
            )
        system = (
            {"parts": [{"text": "\n".join(system_parts)}]}
            if system_parts
            else None
        )
        return system, contents

    async def health(self) -> ProviderHealth:
        caps = [c.value for c in self.capabilities()]
        local = local_config_health(
            self._config, require_api_key=True, capabilities=caps
        )
        if local is not None:
            return local
        try:
            url = f"{self._base_url()}/v1beta/models"
            result, latency = await timed_call(
                self._http.request(
                    "GET",
                    url,
                    headers={"x-goog-api-key": self._config.api_key},
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
                version="v1beta",
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
            system, contents = self._to_contents(request)
            payload: dict[str, Any] = {
                "contents": contents,
                "generationConfig": {
                    "temperature": (
                        request.temperature
                        if request.temperature is not None
                        else self._config.temperature
                    ),
                    "maxOutputTokens": (
                        request.max_tokens
                        if request.max_tokens is not None
                        else self._config.max_tokens
                    ),
                },
            }
            if system:
                payload["systemInstruction"] = system
            if request.json_mode:
                payload["generationConfig"]["responseMimeType"] = (
                    "application/json"
                )

            url = f"{self._model_path(model)}:generateContent"
            result, latency = await timed_call(
                self._http.request(
                    "POST",
                    url,
                    headers={
                        "x-goog-api-key": self._config.api_key,
                        "Content-Type": "application/json",
                    },
                    json_body=payload,
                )
            )
            ensure_success(result, provider_id=self.provider_id)
            body = result.json_body if isinstance(result.json_body, dict) else {}

            # Safety block
            prompt_feedback = body.get("promptFeedback") or {}
            if prompt_feedback.get("blockReason"):
                raise ProviderSafetyBlockedError(
                    self.provider_id,
                    f"Safety blocked: {prompt_feedback.get('blockReason')}",
                )

            candidates = body.get("candidates") or []
            if not candidates:
                raise ProviderSafetyBlockedError(
                    self.provider_id,
                    "No candidates (possible safety block)",
                )
            candidate = candidates[0]
            finish = candidate.get("finishReason")
            if str(finish or "").upper() in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"}:
                raise ProviderSafetyBlockedError(
                    self.provider_id,
                    f"Candidate finishReason={finish}",
                )
            parts = ((candidate.get("content") or {}).get("parts")) or []
            content = "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))
            usage_meta = body.get("usageMetadata") or {}
            usage = TokenUsage(
                prompt_tokens=int(usage_meta.get("promptTokenCount") or 0),
                completion_tokens=int(
                    usage_meta.get("candidatesTokenCount") or 0
                ),
                total_tokens=int(usage_meta.get("totalTokenCount") or 0),
            )
            return AIResponse(
                provider_id=self.provider_id,
                model=model,
                content=content,
                finish_reason=map_finish_reason(finish),
                usage=usage,
                latency_ms=round(latency, 3),
                request_id=result.request_id,
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
            finish_reason=response.finish_reason,
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
