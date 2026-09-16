"""STEP 11-1/11-2 — AI Provider 공통 DTO."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from stock_platform.ai.providers.health_status import HealthStatus

__all__ = [
    "AIAnalyzeRequest",
    "AIChatRequest",
    "AIEmbeddingRequest",
    "AIEmbeddingResponse",
    "AIResponse",
    "ChatMessage",
    "Citation",
    "FinishReason",
    "HealthStatus",
    "ProviderErrorInfo",
    "ProviderHealth",
    "StreamChunk",
    "TokenUsage",
]


class FinishReason(StrEnum):
    STOP = "STOP"
    LENGTH = "LENGTH"
    TOOL_CALL = "TOOL_CALL"
    CONTENT_FILTER = "CONTENT_FILTER"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(slots=True)
class Citation:
    title: str | None = None
    url: str | None = None
    snippet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
        }


@dataclass(slots=True)
class ProviderErrorInfo:
    code: str
    message: str
    retryable: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "detail": self.detail,
        }


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(slots=True)
class AIChatRequest:
    messages: list[ChatMessage]
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    json_mode: bool = False
    # STEP12-3 §18: 지정 시 AIManager가 Provider 설정(AIProviderConfig
    # .timeout_seconds)보다 이 값을 우선한다 — 호출자가 자신이 기록/추적하는
    # timeout(예: Generation Run.timeout_seconds)을 실제 호출에 반영할 수
    # 있게 한다. 미지정 시 기존 동작(Provider 설정값) 그대로 유지.
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AIAnalyzeRequest:
    content: str
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AIEmbeddingRequest:
    texts: list[str]
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AIResponse:
    provider_id: str
    model: str
    content: str
    finish_reason: FinishReason = FinishReason.STOP
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: float = 0.0
    confidence: float | None = None
    reasoning_summary: str | None = None
    citations: list[Citation] = field(default_factory=list)
    error: ProviderErrorInfo | None = None
    request_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "model": self.model,
            "content": self.content,
            "finish_reason": self.finish_reason.value,
            "usage": self.usage.to_dict(),
            "latency_ms": self.latency_ms,
            "confidence": self.confidence,
            "reasoning_summary": self.reasoning_summary,
            "citations": [c.to_dict() for c in self.citations],
            "error": self.error.to_dict() if self.error else None,
            "request_id": self.request_id,
            "ok": self.ok,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(slots=True)
class AIEmbeddingResponse:
    provider_id: str
    model: str
    vectors: list[list[float]]
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: float = 0.0
    error: ProviderErrorInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "model": self.model,
            "vector_count": len(self.vectors),
            "dimensions": len(self.vectors[0]) if self.vectors else 0,
            "usage": self.usage.to_dict(),
            "latency_ms": self.latency_ms,
            "error": self.error.to_dict() if self.error else None,
            "ok": self.error is None,
        }


@dataclass(slots=True)
class ProviderHealth:
    provider_id: str
    status: HealthStatus
    enabled: bool = False
    configured: bool = False
    latency_ms: float | None = None
    model: str | None = None
    endpoint_masked: str | None = None
    version: str | None = None
    message: str | None = None
    capabilities: list[str] = field(default_factory=list)
    sanitized_error_code: str | None = None
    circuit_state: str | None = None
    checked_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider": self.provider_id,
            "status": self.status.value,
            "enabled": self.enabled,
            "configured": self.configured,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "endpoint": self.endpoint_masked,
            "endpoint_masked": self.endpoint_masked,
            "version": self.version,
            "message": self.message,
            "capabilities": list(self.capabilities),
            "sanitized_error_code": self.sanitized_error_code,
            "circuit_state": self.circuit_state,
            "checked_at": self.checked_at.isoformat(),
            "last_success_at": (
                self.last_success_at.isoformat()
                if self.last_success_at
                else None
            ),
            "last_error_at": (
                self.last_error_at.isoformat()
                if self.last_error_at
                else None
            ),
        }


@dataclass(slots=True)
class StreamChunk:
    delta: str
    done: bool = False
    finish_reason: FinishReason | None = None
    usage: TokenUsage | None = None
