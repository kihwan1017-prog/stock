"""STEP 11-1 — Mock AI Provider (실 API 호출 없음)."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

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
    HealthStatus,
    ProviderErrorInfo,
    ProviderHealth,
    TokenUsage,
)
from stock_platform.ai.providers.errors import (
    AIProviderError,
    ProviderTimeoutError,
)

# 테스트/데모용 고정 시그널
FIXED_SIGNALS = ("BUY", "HOLD", "SELL")


class MockAIProvider(AIProvider):
    """고정 응답·지연·오류·타임아웃 시뮬레이션."""

    provider_id = "mock"
    display_name = "Mock Provider"

    def __init__(self, config: AIProviderConfig | None = None) -> None:
        self._config = config or AIProviderConfig(
            provider_id="mock",
            enabled=True,
            is_default=True,
            model="mock-v1",
        )
        self.provider_id = self._config.provider_id
        self._initialized = False
        self._call_count = 0

    def capabilities(self) -> frozenset[AICapability]:
        return frozenset(
            {
                AICapability.CHAT,
                AICapability.NEWS,
                AICapability.JSON,
                AICapability.STREAM,
                AICapability.EMBEDDING,
                AICapability.SUMMARIZE,
                AICapability.STRATEGY,
                AICapability.CHART,
            }
        )

    async def initialize(self) -> None:
        self._initialized = True

    async def shutdown(self) -> None:
        self._initialized = False

    async def health(self) -> ProviderHealth:
        started = time.perf_counter()
        if not self._config.enabled:
            return ProviderHealth(
                provider_id=self.provider_id,
                status=HealthStatus.DISABLED,
                enabled=False,
                configured=True,
                model=self._config.model,
                version="1.0.0",
                message="Mock provider disabled",
                capabilities=[c.value for c in self.capabilities()],
            )
        latency = (time.perf_counter() - started) * 1000.0
        return ProviderHealth(
            provider_id=self.provider_id,
            status=HealthStatus.HEALTHY,
            enabled=True,
            configured=True,
            latency_ms=round(latency, 3),
            model=self._config.model,
            version="1.0.0",
            message="Mock OK",
            capabilities=[c.value for c in self.capabilities()],
        )

    def _signal(self) -> str:
        extra = self._config.extra or {}
        raw = str(extra.get("fixed_signal") or "HOLD").upper()
        return raw if raw in FIXED_SIGNALS else "HOLD"

    async def _simulate_preflight(self) -> None:
        extra = self._config.extra or {}
        latency_ms = float(extra.get("latency_ms") or 0.0)
        if latency_ms > 0:
            await asyncio.sleep(latency_ms / 1000.0)
        if bool(extra.get("simulate_timeout")):
            raise ProviderTimeoutError(self.provider_id, "Mock timeout")
        if bool(extra.get("simulate_error")):
            raise AIProviderError(
                "Mock simulated error",
                code="MOCK_ERROR",
                provider_id=self.provider_id,
                retryable=True,
            )

    async def chat(self, request: AIChatRequest) -> AIResponse:
        started = time.perf_counter()
        self._call_count += 1
        try:
            await self._simulate_preflight()
        except AIProviderError as exc:
            return AIResponse(
                provider_id=self.provider_id,
                model=request.model or self._config.model,
                content="",
                finish_reason=FinishReason.ERROR
                if exc.code != "TIMEOUT"
                else FinishReason.TIMEOUT,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error=ProviderErrorInfo(
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable,
                ),
            )

        signal = self._signal()
        content = signal
        if request.json_mode:
            joined = " ".join(m.content for m in request.messages)
            if "NEWS_ANALYSIS" in joined or "UNTRUSTED_NEWS" in joined:
                content = json.dumps(
                    {
                        "schema_version": "1.0",
                        "task_type": "NEWS_ANALYSIS",
                        "confidence": 0.55,
                        "reasoning_summary": "Mock news analysis (reference only)",
                        "result": {
                            "sentiment": "NEUTRAL",
                            "importance": "LOW",
                            "market_relevance": "UNKNOWN",
                            "summary": "Mock news summary",
                            "event_summary": "Mock event",
                            "key_facts": [],
                            "risks": [],
                            "related_symbols": [],
                            "topics": ["mock"],
                        },
                        "warnings": [],
                        "citations": [{"source": "body", "ref": "title"}],
                    },
                    ensure_ascii=False,
                )
            elif (
                "DISCLOSURE_ANALYSIS" in joined
                or "UNTRUSTED_DISCLOSURE" in joined
            ):
                content = json.dumps(
                    {
                        "schema_version": "1.0",
                        "task_type": "DISCLOSURE_ANALYSIS",
                        "confidence": 0.55,
                        "reasoning_summary": "Mock disclosure analysis",
                        "result": {
                            "event_importance": "LOW",
                            "disclosure_category": "OTHER",
                            "correction_status": "UNKNOWN",
                            "executive_summary": "Mock disclosure summary",
                            "key_changes": [],
                            "financial_impacts": [],
                            "risks": [],
                            "related_symbols": [],
                        },
                        "warnings": [],
                        "citations": [{"source": "meta", "ref": "receipt"}],
                    },
                    ensure_ascii=False,
                )
            elif "CHART_ANALYSIS" in joined or "timeframe=" in joined:
                content = json.dumps(
                    {
                        "schema_version": "1.0",
                        "task_type": "CHART_ANALYSIS",
                        "confidence": 0.5,
                        "reasoning_summary": "Mock chart analysis (reference only)",
                        "result": {
                            "trend": "SIDEWAYS",
                            "trend_strength": "WEAK",
                            "momentum": "NEUTRAL",
                            "volatility": "NORMAL",
                            "volume_condition": "NORMAL",
                            "summary": "Mock chart summary",
                            "support_levels": [],
                            "resistance_levels": [],
                            "notable_patterns": [],
                            "indicator_interpretations": [],
                            "bullish_factors": [],
                            "bearish_factors": [],
                            "uncertainty_factors": ["mock_data"],
                            "indicators_used": ["rsi14", "ma20"],
                        },
                        "warnings": [],
                        "citations": [{"source": "snapshot", "ref": "candles"}],
                    },
                    ensure_ascii=False,
                )
            elif "MARKET_ANALYSIS" in joined or "market overview" in joined.lower():
                content = json.dumps(
                    {
                        "schema_version": "1.0",
                        "task_type": "MARKET_ANALYSIS",
                        "confidence": 0.5,
                        "reasoning_summary": "Mock market overview",
                        "result": {
                            "market_regime": "MIXED",
                            "breadth": "MODERATE",
                            "volatility_environment": "NORMAL",
                            "liquidity_condition": "NORMAL",
                            "volume_condition": "NORMAL",
                            "executive_summary": "Mock market summary",
                            "major_drivers": [],
                            "leading_groups": [],
                            "lagging_groups": [],
                            "risk_factors": [],
                            "positive_factors": [],
                            "uncertainty_factors": ["mock_data"],
                        },
                        "warnings": [],
                        "citations": [{"source": "snapshot", "ref": "symbols"}],
                    },
                    ensure_ascii=False,
                )
            else:
                content = f'{{"signal":"{signal}","confidence":0.5}}'
        elif request.messages:
            last = request.messages[-1].content.strip().upper()
            if last in FIXED_SIGNALS:
                content = last

        latency = (time.perf_counter() - started) * 1000.0
        return AIResponse(
            provider_id=self.provider_id,
            model=request.model or self._config.model,
            content=content,
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(
                prompt_tokens=10,
                completion_tokens=3,
                total_tokens=13,
            ),
            latency_ms=round(latency, 3),
            confidence=0.5,
            reasoning_summary=f"Mock fixed signal={signal}",
            raw={"call_count": self._call_count},
        )

    async def analyze_news(self, request: AIAnalyzeRequest) -> AIResponse:
        started = time.perf_counter()
        await self._simulate_preflight()
        signal = self._signal()
        return AIResponse(
            provider_id=self.provider_id,
            model=request.model or self._config.model,
            content=f"NEWS:{signal}",
            finish_reason=FinishReason.STOP,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            confidence=0.4,
            reasoning_summary="Mock news analysis",
        )

    async def generate_strategy(self, request: AIAnalyzeRequest) -> AIResponse:
        """인터페이스만 — 주문 연결 없음."""

        started = time.perf_counter()
        await self._simulate_preflight()
        signal = self._signal()
        return AIResponse(
            provider_id=self.provider_id,
            model=request.model or self._config.model,
            content=f"STRATEGY_SKETCH:{signal}",
            finish_reason=FinishReason.STOP,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            confidence=0.3,
            reasoning_summary="Mock strategy sketch (no orders)",
        )

    async def embedding(
        self, request: AIEmbeddingRequest
    ) -> AIEmbeddingResponse:
        started = time.perf_counter()
        await self._simulate_preflight()
        vectors = [[0.1, 0.2, 0.3] for _ in request.texts]
        return AIEmbeddingResponse(
            provider_id=self.provider_id,
            model=request.model or self._config.model,
            vectors=vectors,
            usage=TokenUsage(
                prompt_tokens=len(request.texts),
                total_tokens=len(request.texts),
            ),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )

    @property
    def call_count(self) -> int:
        return self._call_count

    def describe(self) -> dict[str, Any]:
        base = super().describe()
        base["enabled"] = self._config.enabled
        base["model"] = self._config.model
        base["is_default"] = self._config.is_default
        return base
