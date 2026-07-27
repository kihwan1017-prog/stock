"""STEP 11-2 — Ollama Provider (로컬 HTTP)."""

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
    require_ready,
    timed_call,
    unsupported_response,
)
from stock_platform.ai.providers.http_client import (
    AIProviderHttpClient,
    ensure_success,
)


class OllamaProvider(AIProvider):
    provider_id = "ollama"
    display_name = "Ollama"

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
            self._config.api_endpoint or "http://127.0.0.1:11434",
            allow_localhost=True,
            provider_id=self.provider_id,
        )

    async def health(self) -> ProviderHealth:
        caps = [c.value for c in self.capabilities()]
        local = local_config_health(
            self._config, require_api_key=False, capabilities=caps
        )
        if local is not None:
            return local
        try:
            result, latency = await timed_call(
                self._http.request("GET", f"{self._base_url()}/api/tags")
            )
            ensure_success(result, provider_id=self.provider_id)
            body = result.json_body if isinstance(result.json_body, dict) else {}
            models = body.get("models") or []
            names = {
                str(m.get("name") or m.get("model") or "")
                for m in models
                if isinstance(m, dict)
            }
            model = self._config.model
            if model:
                matched = any(
                    n == model or n.split(":")[0] == model.split(":")[0]
                    for n in names
                )
                if not matched:
                    return ProviderHealth(
                        provider_id=self.provider_id,
                        status=HealthStatus.MODEL_NOT_FOUND,
                        enabled=True,
                        configured=True,
                        latency_ms=round(latency, 3),
                        model=model,
                        endpoint_masked=mask_endpoint(self._base_url()),
                        message=f"Model '{model}' not found",
                        capabilities=caps,
                        sanitized_error_code="MODEL_NOT_FOUND",
                    )
            return ProviderHealth(
                provider_id=self.provider_id,
                status=HealthStatus.HEALTHY,
                enabled=True,
                configured=True,
                latency_ms=round(latency, 3),
                model=model,
                endpoint_masked=mask_endpoint(self._base_url()),
                version="ollama",
                message=f"tags OK ({len(names)} models)",
                capabilities=caps,
            )
        except AIProviderError as exc:
            status = HealthStatus.OFFLINE
            if exc.code == "TIMEOUT":
                status = HealthStatus.TIMEOUT
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
            require_ready(self._config, require_api_key=False)
            payload: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": m.role, "content": m.content}
                    for m in request.messages
                ],
                "stream": False,
                "options": {
                    "temperature": (
                        request.temperature
                        if request.temperature is not None
                        else self._config.temperature
                    ),
                    "num_predict": (
                        request.max_tokens
                        if request.max_tokens is not None
                        else self._config.max_tokens
                    ),
                },
            }
            if request.json_mode:
                payload["format"] = "json"

            result, latency = await timed_call(
                self._http.request(
                    "POST",
                    f"{self._base_url()}/api/chat",
                    json_body=payload,
                )
            )
            ensure_success(result, provider_id=self.provider_id)
            body = result.json_body if isinstance(result.json_body, dict) else {}
            message = body.get("message") or {}
            content = str(message.get("content") or "")
            usage = TokenUsage(
                prompt_tokens=int(body.get("prompt_eval_count") or 0),
                completion_tokens=int(body.get("eval_count") or 0),
                total_tokens=int(body.get("prompt_eval_count") or 0)
                + int(body.get("eval_count") or 0),
            )
            return AIResponse(
                provider_id=self.provider_id,
                model=str(body.get("model") or model),
                content=content,
                finish_reason=FinishReason.STOP,
                usage=usage,
                latency_ms=round(latency, 3),
            )
        except AIProviderError as exc:
            return error_response(
                provider_id=self.provider_id, model=model, exc=exc
            )

    async def chat_stream(
        self, request: AIChatRequest
    ) -> AsyncIterator[StreamChunk]:
        model = request.model or self._config.model
        require_ready(self._config, require_api_key=False)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in request.messages
            ],
            "stream": True,
        }
        async for line in self._http.stream_lines(
            "POST",
            f"{self._base_url()}/api/chat",
            json_body=payload,
        ):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            delta = str(((obj.get("message") or {}).get("content")) or "")
            done = bool(obj.get("done"))
            if delta:
                yield StreamChunk(delta=delta, done=False)
            if done:
                usage = TokenUsage(
                    prompt_tokens=int(obj.get("prompt_eval_count") or 0),
                    completion_tokens=int(obj.get("eval_count") or 0),
                    total_tokens=int(obj.get("prompt_eval_count") or 0)
                    + int(obj.get("eval_count") or 0),
                )
                yield StreamChunk(
                    delta="",
                    done=True,
                    finish_reason=FinishReason.STOP,
                    usage=usage,
                )
                return

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
