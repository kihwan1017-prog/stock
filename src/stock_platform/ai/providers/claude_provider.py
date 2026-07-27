"""STEP 11-2 — Anthropic Claude Provider (Messages API)."""

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
from stock_platform.ai.providers.errors import AIProviderError
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

ANTHROPIC_VERSION = "2023-06-01"


class ClaudeProvider(AIProvider):
    provider_id = "claude"
    display_name = "Claude (Anthropic)"

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
            self._config.api_endpoint or "https://api.anthropic.com",
            allow_localhost=False,
            provider_id=self.provider_id,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._config.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _split_messages(
        self, request: AIChatRequest
    ) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        messages: list[dict[str, Any]] = []
        for msg in request.messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            else:
                role = "assistant" if msg.role == "assistant" else "user"
                messages.append({"role": role, "content": msg.content})
        if not messages:
            messages = [{"role": "user", "content": "ping"}]
        system = "\n".join(system_parts) if system_parts else None
        return system, messages

    @staticmethod
    def _content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "".join(parts)
        return str(content or "")

    async def health(self) -> ProviderHealth:
        caps = [c.value for c in self.capabilities()]
        local = local_config_health(
            self._config, require_api_key=True, capabilities=caps
        )
        if local is not None:
            return local
        # Anthropic에 저비용 public models endpoint가 없으므로
        # 최소 messages 호출 없이 configured만 HEALTHY로 보고,
        # 실제 probe는 Admin health-check/test에서 수행.
        return ProviderHealth(
            provider_id=self.provider_id,
            status=HealthStatus.HEALTHY,
            enabled=True,
            configured=True,
            latency_ms=0.0,
            model=self._config.model,
            endpoint_masked=mask_endpoint(self._base_url()),
            version=ANTHROPIC_VERSION,
            message="Configured (use health-check for live probe)",
            capabilities=caps,
        )

    async def chat(self, request: AIChatRequest) -> AIResponse:
        model = request.model or self._config.model
        try:
            require_ready(self._config, require_api_key=True)
            system, messages = self._split_messages(request)
            payload: dict[str, Any] = {
                "model": model,
                "max_tokens": (
                    request.max_tokens
                    if request.max_tokens is not None
                    else self._config.max_tokens
                ),
                "messages": messages,
            }
            if system:
                payload["system"] = system
            if request.temperature is not None:
                payload["temperature"] = request.temperature
            elif self._config.temperature is not None:
                payload["temperature"] = self._config.temperature

            result, latency = await timed_call(
                self._http.request(
                    "POST",
                    f"{self._base_url()}/v1/messages",
                    headers=self._headers(),
                    json_body=payload,
                )
            )
            ensure_success(result, provider_id=self.provider_id)
            body = result.json_body if isinstance(result.json_body, dict) else {}
            content = self._content_text(body.get("content"))
            usage_raw = body.get("usage") or {}
            usage = TokenUsage(
                prompt_tokens=int(usage_raw.get("input_tokens") or 0),
                completion_tokens=int(usage_raw.get("output_tokens") or 0),
                total_tokens=int(usage_raw.get("input_tokens") or 0)
                + int(usage_raw.get("output_tokens") or 0),
            )
            return AIResponse(
                provider_id=self.provider_id,
                model=str(body.get("model") or model),
                content=content,
                finish_reason=map_finish_reason(body.get("stop_reason")),
                usage=usage,
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
        # Foundation: non-stream fallback chunk
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

    async def live_health_probe(self) -> ProviderHealth:
        """Admin health-check 전용 — 최소 messages 1회."""

        from stock_platform.ai.providers.dto import ChatMessage

        response = await self.chat(
            AIChatRequest(
                messages=[
                    ChatMessage(role="user", content="Return exactly: OK")
                ],
                max_tokens=8,
            )
        )
        caps = [c.value for c in self.capabilities()]
        if response.ok:
            return ProviderHealth(
                provider_id=self.provider_id,
                status=HealthStatus.HEALTHY,
                enabled=True,
                configured=True,
                latency_ms=response.latency_ms,
                model=response.model,
                endpoint_masked=mask_endpoint(self._base_url()),
                message="live probe OK",
                capabilities=caps,
            )
        code = response.error.code if response.error else "ERROR"
        status = HealthStatus.ERROR
        if code == "AUTH_FAILED":
            status = HealthStatus.AUTH_FAILED
        elif code == "RATE_LIMITED":
            status = HealthStatus.RATE_LIMITED
        elif code == "TIMEOUT":
            status = HealthStatus.TIMEOUT
        return ProviderHealth(
            provider_id=self.provider_id,
            status=status,
            enabled=True,
            configured=True,
            latency_ms=response.latency_ms,
            model=self._config.model,
            endpoint_masked=mask_endpoint(self._config.api_endpoint),
            message=response.error.message if response.error else "failed",
            capabilities=caps,
            sanitized_error_code=code,
        )
