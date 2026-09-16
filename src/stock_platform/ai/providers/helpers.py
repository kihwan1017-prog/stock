"""STEP 11-2 — Provider 공통 헬퍼."""

from __future__ import annotations

import time
from typing import Any

from stock_platform.ai.providers.config import AIProviderConfig
from stock_platform.ai.providers.dto import (
    AIAnalyzeRequest,
    AIChatRequest,
    AIEmbeddingRequest,
    AIEmbeddingResponse,
    AIResponse,
    FinishReason,
    ProviderErrorInfo,
    ProviderHealth,
    TokenUsage,
)
from stock_platform.ai.providers.endpoint_policy import mask_endpoint
from stock_platform.ai.providers.errors import (
    AIProviderError,
    ProviderCapabilityError,
    ProviderDisabledError,
    ProviderNotConfiguredError,
)
from stock_platform.ai.providers.health_status import HealthStatus


def unsupported_response(
    *,
    provider_id: str,
    model: str,
    capability: str,
) -> AIResponse:
    err = ProviderCapabilityError(provider_id, capability)
    return AIResponse(
        provider_id=provider_id,
        model=model,
        content="",
        finish_reason=FinishReason.ERROR,
        error=ProviderErrorInfo(
            code=err.code,
            message=err.message,
            retryable=False,
            detail={"capability": capability},
        ),
    )


def error_response(
    *,
    provider_id: str,
    model: str,
    exc: AIProviderError,
    latency_ms: float = 0.0,
    request_id: str | None = None,
) -> AIResponse:
    finish = FinishReason.ERROR
    if exc.code == "TIMEOUT":
        finish = FinishReason.TIMEOUT
    elif exc.code == "SAFETY_BLOCKED":
        finish = FinishReason.SAFETY_BLOCKED
    return AIResponse(
        provider_id=provider_id,
        model=model,
        content="",
        finish_reason=finish,
        latency_ms=latency_ms,
        request_id=request_id,
        error=ProviderErrorInfo(
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
        ),
    )


def require_ready(
    config: AIProviderConfig,
    *,
    require_api_key: bool,
) -> None:
    if not config.enabled:
        raise ProviderDisabledError(config.provider_id)
    if require_api_key and not config.api_key.strip():
        raise ProviderNotConfiguredError(config.provider_id)
    if not require_api_key and not config.api_endpoint.strip():
        raise ProviderNotConfiguredError(
            config.provider_id,
            "Endpoint not configured",
        )


def local_config_health(
    config: AIProviderConfig,
    *,
    require_api_key: bool,
    capabilities: list[str],
    version: str = "11.2",
) -> ProviderHealth | None:
    """로컬 설정만으로 결정 가능한 Health. None이면 원격 probe 필요."""

    caps = capabilities
    endpoint = mask_endpoint(config.api_endpoint)
    if not config.enabled:
        return ProviderHealth(
            provider_id=config.provider_id,
            status=HealthStatus.DISABLED,
            enabled=False,
            configured=False,
            model=config.model,
            endpoint_masked=endpoint,
            version=version,
            message="Disabled by config",
            capabilities=caps,
        )
    configured = bool(config.api_key.strip()) if require_api_key else bool(
        config.api_endpoint.strip()
    )
    if require_api_key and config.api_key.strip() and config.api_endpoint.strip():
        configured = True
    if not configured:
        return ProviderHealth(
            provider_id=config.provider_id,
            status=HealthStatus.NOT_CONFIGURED,
            enabled=True,
            configured=False,
            model=config.model,
            endpoint_masked=endpoint,
            version=version,
            message="Credential/endpoint missing",
            capabilities=caps,
            sanitized_error_code="NOT_CONFIGURED",
        )
    return None


def map_finish_reason(raw: str | None) -> FinishReason:
    value = (raw or "").lower()
    mapping = {
        "stop": FinishReason.STOP,
        "end_turn": FinishReason.STOP,
        "stop_sequence": FinishReason.STOP,
        "length": FinishReason.LENGTH,
        "max_tokens": FinishReason.LENGTH,
        "tool_calls": FinishReason.TOOL_CALL,
        "tool_use": FinishReason.TOOL_CALL,
        "content_filter": FinishReason.CONTENT_FILTER,
        "safety": FinishReason.SAFETY_BLOCKED,
        "blocked": FinishReason.SAFETY_BLOCKED,
    }
    return mapping.get(value, FinishReason.UNKNOWN)


def usage_from_openai(data: dict[str, Any] | None) -> TokenUsage:
    data = data or {}
    prompt = int(data.get("prompt_tokens") or data.get("input_tokens") or 0)
    completion = int(
        data.get("completion_tokens") or data.get("output_tokens") or 0
    )
    total = int(data.get("total_tokens") or (prompt + completion))
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


async def timed_call(coro):
    started = time.perf_counter()
    result = await coro
    latency = (time.perf_counter() - started) * 1000.0
    return result, latency
