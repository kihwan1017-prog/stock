"""STEP 11-2 — AIManager (선택·Fallback·Retry·Timeout·Circuit·Metrics·Health Cache)."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

from stock_platform.ai.providers.base import AIProvider
from stock_platform.ai.providers.capability import AICapability
from stock_platform.ai.providers.circuit_breaker import CircuitBreaker
from stock_platform.ai.providers.config import AIProviderConfig
from stock_platform.ai.providers.dto import (
    AIChatRequest,
    AIResponse,
    FinishReason,
    ProviderErrorInfo,
    ProviderHealth,
)
from stock_platform.ai.providers.errors import (
    AIProviderError,
    ProviderCapabilityError,
    ProviderCircuitOpenError,
)
from stock_platform.ai.providers.health_status import HealthStatus
from stock_platform.ai.providers.metrics import HealthCache, ProviderMetrics
from stock_platform.ai.providers.registry import (
    AIProviderRegistry,
    build_default_registry,
)
from stock_platform.ai.providers.security import sanitize_for_log

logger = structlog.get_logger(__name__)

# Manager만 재시도. Provider HTTP는 재시도하지 않음.
# 최대 호출 = (retry_max + 1) × fallback 체인 길이


@dataclass
class AIManager:
    """Provider 오케스트레이션 — 자동매매/주문과 무관."""

    registry: AIProviderRegistry
    _circuits: dict[str, CircuitBreaker] = field(default_factory=dict)
    _metrics: dict[str, ProviderMetrics] = field(
        default_factory=lambda: defaultdict(ProviderMetrics)
    )
    _health_cache: HealthCache = field(default_factory=lambda: HealthCache(30.0))
    _initialized: bool = False
    external_call_counter: int = 0
    config_source: str = "ENV"

    @classmethod
    def create_default(cls) -> AIManager:
        return cls(registry=build_default_registry())

    def _circuit_for(self, provider_id: str) -> CircuitBreaker:
        if provider_id not in self._circuits:
            cfg = self.registry.get_config(provider_id)
            self._circuits[provider_id] = CircuitBreaker(
                failure_threshold=(
                    cfg.circuit_failure_threshold if cfg else 3
                ),
                reset_seconds=(
                    cfg.circuit_reset_seconds if cfg else 30.0
                ),
            )
        return self._circuits[provider_id]

    def _config(self, provider_id: str) -> AIProviderConfig | None:
        return self.registry.get_config(provider_id)

    async def initialize(self) -> None:
        for provider in self.registry.list_providers():
            await provider.initialize()
        self._initialized = True

    async def shutdown(self) -> None:
        for provider in self.registry.list_providers():
            await provider.shutdown()
        self._initialized = False

    def list_providers(self) -> list[dict[str, Any]]:
        return self.registry.describe_all()

    def get_provider(self, provider_id: str) -> AIProvider | None:
        return self.registry.get(provider_id)

    def select_provider(
        self,
        *,
        provider_id: str | None = None,
        capability: AICapability | None = None,
    ) -> AIProvider:
        if provider_id:
            provider = self.registry.require(provider_id)
            if capability and not provider.supports(capability):
                raise ProviderCapabilityError(provider_id, capability.value)
            return provider
        if capability is not None:
            candidates = self.registry.providers_with_capability(capability)
            if not candidates:
                raise ProviderCapabilityError("*", capability.value)
            return candidates[0]
        default = self.registry.default_provider()
        if default is None:
            raise AIProviderError(
                "No enabled AI provider",
                code="NO_PROVIDER",
            )
        return default

    async def health(
        self,
        provider_id: str | None = None,
        *,
        use_cache: bool = True,
        live_probe: bool = False,
    ) -> list[ProviderHealth]:
        targets = (
            [self.registry.require(provider_id)]
            if provider_id
            else self.registry.list_providers()
        )
        results: list[ProviderHealth] = []
        for provider in targets:
            pid = provider.provider_id
            if use_cache and not live_probe:
                cached = self._health_cache.get(pid)
                if cached is not None:
                    # reconstruct minimal
                    results.append(
                        ProviderHealth(
                            provider_id=pid,
                            status=HealthStatus(
                                cached.get("status", "UNKNOWN")
                            ),
                            enabled=bool(cached.get("enabled")),
                            configured=bool(cached.get("configured")),
                            latency_ms=cached.get("latency_ms"),
                            model=cached.get("model"),
                            endpoint_masked=cached.get("endpoint_masked"),
                            version=cached.get("version"),
                            message=cached.get("message"),
                            capabilities=list(cached.get("capabilities") or []),
                            sanitized_error_code=cached.get(
                                "sanitized_error_code"
                            ),
                            circuit_state=cached.get("circuit_state"),
                        )
                    )
                    continue

            circuit = self._circuit_for(pid)
            if not circuit.allow():
                health = ProviderHealth(
                    provider_id=pid,
                    status=HealthStatus.CIRCUIT_OPEN,
                    enabled=bool(
                        (self._config(pid) or AIProviderConfig(pid)).enabled
                    ),
                    configured=True,
                    message="Circuit breaker open",
                    capabilities=[c.value for c in provider.capabilities()],
                    circuit_state=circuit.state.value,
                    sanitized_error_code="CIRCUIT_OPEN",
                )
                results.append(health)
                self._health_cache.set(pid, health.to_dict())
                continue
            try:
                if live_probe and hasattr(provider, "live_health_probe"):
                    health = await provider.live_health_probe()  # type: ignore[misc]
                else:
                    health = await provider.health()
                health.circuit_state = circuit.state.value
                metrics = self._metrics[pid]
                health.last_success_at = metrics.last_success_at
                health.last_error_at = metrics.last_failure_at
            except Exception as exc:  # noqa: BLE001
                health = ProviderHealth(
                    provider_id=pid,
                    status=HealthStatus.ERROR,
                    message=str(exc),
                    capabilities=[c.value for c in provider.capabilities()],
                    sanitized_error_code=type(exc).__name__,
                    circuit_state=circuit.state.value,
                )
            results.append(health)
            self._health_cache.set(pid, health.to_dict())
        return results

    def cached_health_snapshot(self) -> list[dict[str, Any]]:
        """Dashboard/Telegram용 — 캐시만, 외부 호출 0."""

        rows: list[dict[str, Any]] = []
        for provider in self.registry.list_providers():
            pid = provider.provider_id
            cached = self._health_cache.get(pid)
            cfg = self._config(pid)
            metrics = self._metrics[pid]
            circuit = self._circuit_for(pid)
            if cached:
                row = dict(cached)
            else:
                # 로컬 설정 스냅샷 (네트워크 없음)
                enabled = bool(cfg.enabled) if cfg else False
                configured = False
                status = "DISABLED"
                if enabled and pid == "mock":
                    status = "HEALTHY"
                    configured = True
                elif enabled and cfg and cfg.api_key.strip():
                    configured = True
                    status = "NOT_CONFIGURED"  # live 미검증
                elif enabled and cfg and cfg.api_endpoint.strip() and pid in {
                    "ollama",
                    "openai_compatible",
                }:
                    configured = True
                    status = "NOT_CONFIGURED"
                elif enabled:
                    status = "NOT_CONFIGURED"
                row = {
                    "provider_id": pid,
                    "status": status,
                    "enabled": enabled,
                    "configured": configured,
                    "model": cfg.model if cfg else None,
                    "endpoint_masked": None,
                    "capabilities": [c.value for c in provider.capabilities()],
                    "message": "cached snapshot (no live call)",
                }
            row["circuit_state"] = circuit.state.value
            row["metrics"] = metrics.to_dict()
            rows.append(row)
        return rows

    async def chat(
        self,
        request: AIChatRequest,
        *,
        provider_id: str | None = None,
        fallback: bool = True,
    ) -> AIResponse:
        primary = self.select_provider(
            provider_id=provider_id,
            capability=AICapability.CHAT,
        )
        chain = [primary]
        if fallback and provider_id is None:
            for candidate in self.registry.providers_with_capability(
                AICapability.CHAT
            ):
                if candidate.provider_id != primary.provider_id:
                    chain.append(candidate)

        last_error: AIResponse | None = None
        for provider in chain:
            response = await self._chat_with_resilience(provider, request)
            if response.ok:
                return response
            last_error = response
            logger.warning(
                "ai_provider_chat_failed",
                **sanitize_for_log(
                    {
                        "provider_id": provider.provider_id,
                        "error": (
                            response.error.message
                            if response.error
                            else "unknown"
                        ),
                        "code": (
                            response.error.code if response.error else None
                        ),
                    }
                ),
            )
        return last_error or AIResponse(
            provider_id="*",
            model="",
            content="",
            finish_reason=FinishReason.ERROR,
            error=ProviderErrorInfo(
                code="ALL_PROVIDERS_FAILED",
                message="All providers failed",
            ),
        )

    async def _chat_with_resilience(
        self,
        provider: AIProvider,
        request: AIChatRequest,
    ) -> AIResponse:
        provider_id = provider.provider_id
        circuit = self._circuit_for(provider_id)
        metrics = self._metrics[provider_id]
        cfg = self._config(provider_id)
        timeout = cfg.timeout_seconds if cfg else 30.0
        retries = cfg.retry_max if cfg else 1
        backoff = cfg.retry_backoff_seconds if cfg else 0.2

        if not circuit.allow():
            metrics.record(
                ok=False, latency_ms=0.0, circuit_open=True, error_code="CIRCUIT_OPEN"
            )
            err = ProviderCircuitOpenError(provider_id)
            return AIResponse(
                provider_id=provider_id,
                model=request.model or (cfg.model if cfg else ""),
                content="",
                finish_reason=FinishReason.ERROR,
                error=ProviderErrorInfo(
                    code=err.code,
                    message=err.message,
                    retryable=False,
                ),
            )

        attempt = 0
        while attempt <= retries:
            attempt += 1
            started = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    provider.chat(request),
                    timeout=timeout,
                )
                latency = (time.perf_counter() - started) * 1000.0
                response.latency_ms = round(latency, 3)
                if response.ok:
                    circuit.record_success()
                    metrics.record(
                        ok=True,
                        latency_ms=latency,
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                    )
                    return response
                code = response.error.code if response.error else "ERROR"
                retryable = bool(response.error and response.error.retryable)
                rate_limited = code == "RATE_LIMITED"
                if retryable and attempt <= retries:
                    # Retry-After 존중 (detail에 있을 때)
                    delay = backoff * attempt
                    await asyncio.sleep(delay)
                    continue
                circuit.record_failure()
                metrics.record(
                    ok=False,
                    latency_ms=latency,
                    rate_limited=rate_limited,
                    error_code=code,
                )
                return response
            except TimeoutError:
                latency = (time.perf_counter() - started) * 1000.0
                metrics.record(
                    ok=False, latency_ms=latency, timeout=True, error_code="TIMEOUT"
                )
                if attempt <= retries:
                    await asyncio.sleep(backoff * attempt)
                    continue
                circuit.record_failure()
                return AIResponse(
                    provider_id=provider_id,
                    model=request.model or (cfg.model if cfg else ""),
                    content="",
                    finish_reason=FinishReason.TIMEOUT,
                    latency_ms=latency,
                    error=ProviderErrorInfo(
                        code="TIMEOUT",
                        message=f"Timed out after {timeout}s",
                        retryable=True,
                    ),
                )
            except AIProviderError as exc:
                latency = (time.perf_counter() - started) * 1000.0
                metrics.record(
                    ok=False,
                    latency_ms=latency,
                    rate_limited=exc.code == "RATE_LIMITED",
                    error_code=exc.code,
                )
                if exc.retryable and attempt <= retries:
                    await asyncio.sleep(backoff * attempt)
                    continue
                circuit.record_failure()
                return AIResponse(
                    provider_id=provider_id,
                    model=request.model or (cfg.model if cfg else ""),
                    content="",
                    finish_reason=FinishReason.ERROR,
                    latency_ms=latency,
                    error=ProviderErrorInfo(
                        code=exc.code,
                        message=exc.message,
                        retryable=exc.retryable,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                latency = (time.perf_counter() - started) * 1000.0
                metrics.record(
                    ok=False,
                    latency_ms=latency,
                    error_code=type(exc).__name__,
                )
                circuit.record_failure()
                return AIResponse(
                    provider_id=provider_id,
                    model=request.model or (cfg.model if cfg else ""),
                    content="",
                    finish_reason=FinishReason.ERROR,
                    latency_ms=latency,
                    error=ProviderErrorInfo(
                        code="UNEXPECTED",
                        message=str(exc),
                        retryable=False,
                    ),
                )

        return AIResponse(
            provider_id=provider_id,
            model=request.model or (cfg.model if cfg else ""),
            content="",
            finish_reason=FinishReason.ERROR,
            error=ProviderErrorInfo(
                code="RETRY_EXHAUSTED",
                message="Retries exhausted",
            ),
        )

    async def test_provider(
        self,
        provider_id: str,
        *,
        prompt: str = "Return exactly: OK",
        model: str | None = None,
        max_tokens: int = 32,
    ) -> dict[str, Any]:
        provider = self.registry.require(provider_id)
        cfg = self._config(provider_id)
        if cfg is not None and not cfg.enabled:
            raise AIProviderError(
                "Provider disabled",
                code="DISABLED",
                provider_id=provider_id,
            )
        from stock_platform.ai.providers.dto import ChatMessage

        # 길이 제한
        prompt = prompt[:2000]
        max_tokens = max(1, min(int(max_tokens), 256))

        response = await self._chat_with_resilience(
            provider,
            AIChatRequest(
                messages=[ChatMessage(role="user", content=prompt)],
                model=model,
                max_tokens=max_tokens,
            ),
        )
        # 응답 길이 제한
        content = response.content[:4000]
        payload = response.to_dict()
        payload["content"] = content
        return {
            "provider_id": provider_id,
            "response": payload,
            "metrics": self._metrics[provider_id].to_dict(),
            "circuit": self._circuit_for(provider_id).snapshot(),
            "estimated_cost": None,
        }

    def metrics_snapshot(self) -> dict[str, Any]:
        return {
            provider_id: metrics.to_dict()
            for provider_id, metrics in self._metrics.items()
        }

    def dashboard_block(self) -> dict[str, Any]:
        """Operations Center — 캐시/설정만, 외부 AI 호출 0."""

        items: list[dict[str, Any]] = []
        healthy = 0
        snapshots = {
            row["provider_id"]: row for row in self.cached_health_snapshot()
        }
        config_source = getattr(self, "config_source", "ENV")
        for meta in self.list_providers():
            pid = str(meta.get("id"))
            cfg = self.registry.get_config(pid)
            circuit = self._circuit_for(pid)
            metrics = self._metrics[pid].to_dict()
            snap = snapshots.get(pid) or {}
            status = str(snap.get("status") or "UNKNOWN")
            if status == "HEALTHY":
                healthy += 1
            total = int(metrics.get("total_requests") or 0)
            success = int(metrics.get("successful_requests") or 0)
            failed = int(metrics.get("failed_requests") or 0)
            items.append(
                {
                    "id": pid,
                    "display_name": meta.get("display_name"),
                    "status": status,
                    "enabled": bool(cfg.enabled) if cfg else False,
                    "configured": bool(snap.get("configured")),
                    "model": cfg.model if cfg else meta.get("model"),
                    "endpoint": snap.get("endpoint_masked"),
                    "version": snap.get("version") or (
                        "1.0.0" if pid == "mock" else "11.3"
                    ),
                    "capabilities": meta.get("capabilities") or [],
                    "priority": cfg.priority if cfg else None,
                    "is_default": bool(cfg.is_default) if cfg else False,
                    "latency_ms": metrics.get("average_latency_ms"),
                    "success_rate": (
                        round(success / total, 4) if total else None
                    ),
                    "error_rate": (
                        round(failed / total, 4) if total else None
                    ),
                    "circuit_state": circuit.state.value,
                    "last_check": snap.get("checked_at"),
                    "last_success": metrics.get("last_success_at"),
                    "token_usage": {
                        "input": metrics.get("input_tokens"),
                        "output": metrics.get("output_tokens"),
                        "total": metrics.get("total_tokens"),
                    },
                    "request_count": total,
                    "metrics": metrics,
                    "circuit": circuit.snapshot(),
                    "configuration_source": config_source,
                    "credential_status": snap.get("credential_status"),
                    "reload_required": snap.get("reload_required"),
                    "config_drift": snap.get("config_drift"),
                }
            )
        overall = "HEALTHY" if healthy > 0 else "WARNING"
        return {
            "health": overall,
            "default_provider": (
                self.registry.default_provider().provider_id
                if self.registry.default_provider()
                else None
            ),
            "count": len(items),
            "healthy_count": healthy,
            "items": items,
            "external_calls_on_read": 0,
            "configuration_source": config_source,
        }


_MANAGER: AIManager | None = None


def get_ai_manager() -> AIManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = AIManager.create_default()
    return _MANAGER


def reset_ai_manager(manager: AIManager | None = None) -> AIManager:
    global _MANAGER
    _MANAGER = manager if manager is not None else AIManager.create_default()
    return _MANAGER
