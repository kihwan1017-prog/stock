"""STEP 11-1 — AIProvider 공통 인터페이스 (Async 우선)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from stock_platform.ai.providers.capability import AICapability
from stock_platform.ai.providers.dto import (
    AIAnalyzeRequest,
    AIChatRequest,
    AIEmbeddingRequest,
    AIEmbeddingResponse,
    AIResponse,
    ProviderHealth,
    StreamChunk,
)


class AIProvider(ABC):
    """모든 AI Provider가 구현하는 공통 인터페이스.

    전략 생성·자동 주문은 STEP 11-1에서 호출하지 않는다.
    메서드 시그니처만 정의하여 이후 STEP에서 확장한다.
    """

    provider_id: str
    display_name: str

    @abstractmethod
    def capabilities(self) -> frozenset[AICapability]:
        raise NotImplementedError

    def supports(self, capability: AICapability) -> bool:
        return capability in self.capabilities()

    @abstractmethod
    async def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> ProviderHealth:
        raise NotImplementedError

    @abstractmethod
    async def chat(self, request: AIChatRequest) -> AIResponse:
        raise NotImplementedError

    async def chat_stream(
        self, request: AIChatRequest
    ) -> AsyncIterator[StreamChunk]:
        """기본: 비스트림 chat 결과를 단일 청크로 반환."""

        response = await self.chat(request)
        yield StreamChunk(
            delta=response.content,
            done=True,
            finish_reason=response.finish_reason,
            usage=response.usage,
        )

    async def analyze_news(self, request: AIAnalyzeRequest) -> AIResponse:
        """뉴스 분석 — Foundation에서는 chat 위임 가능."""

        from stock_platform.ai.providers.dto import ChatMessage

        return await self.chat(
            AIChatRequest(
                messages=[
                    ChatMessage(
                        role="system",
                        content="Analyze the news. Reply briefly.",
                    ),
                    ChatMessage(role="user", content=request.content),
                ],
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                metadata=request.metadata,
            )
        )

    async def analyze_chart(self, request: AIAnalyzeRequest) -> AIResponse:
        """차트 분석 — Foundation 스텁 (실제 비전 분석은 후속 STEP)."""

        from stock_platform.ai.providers.dto import ChatMessage

        return await self.chat(
            AIChatRequest(
                messages=[
                    ChatMessage(
                        role="system",
                        content="Analyze the chart context. Reply briefly.",
                    ),
                    ChatMessage(role="user", content=request.content),
                ],
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                metadata=request.metadata,
            )
        )

    async def generate_strategy(self, request: AIAnalyzeRequest) -> AIResponse:
        """전략 생성 — STEP 11-1에서는 인터페이스만 제공.

        실제 자동매매/주문과 연결하지 않는다.
        """

        from stock_platform.ai.providers.dto import ChatMessage

        return await self.chat(
            AIChatRequest(
                messages=[
                    ChatMessage(
                        role="system",
                        content=(
                            "Generate a trading strategy sketch only. "
                            "Do not place orders."
                        ),
                    ),
                    ChatMessage(role="user", content=request.content),
                ],
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                metadata=request.metadata,
            )
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
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                metadata=request.metadata,
            )
        )

    async def embedding(
        self, request: AIEmbeddingRequest
    ) -> AIEmbeddingResponse:
        from stock_platform.ai.providers.errors import ProviderCapabilityError

        raise ProviderCapabilityError(self.provider_id, "EMBEDDING")

    @abstractmethod
    async def shutdown(self) -> None:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "display_name": self.display_name,
            "capabilities": sorted(c.value for c in self.capabilities()),
        }
