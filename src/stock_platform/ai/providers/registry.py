"""STEP 11-1 — Provider Registry."""

from __future__ import annotations

from typing import Any

from stock_platform.ai.providers.base import AIProvider
from stock_platform.ai.providers.capability import AICapability
from stock_platform.ai.providers.config import (
    AIProviderConfig,
    load_provider_configs_from_settings,
)
from stock_platform.ai.providers.claude_provider import ClaudeProvider
from stock_platform.ai.providers.gemini_provider import GeminiProvider
from stock_platform.ai.providers.mock_provider import MockAIProvider
from stock_platform.ai.providers.ollama_provider import OllamaProvider
from stock_platform.ai.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)
from stock_platform.ai.providers.openai_provider import OpenAIProvider


class AIProviderRegistry:
    """Provider 등록·조회."""

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}
        self._configs: dict[str, AIProviderConfig] = {}

    def register(
        self,
        provider: AIProvider,
        config: AIProviderConfig | None = None,
    ) -> None:
        self._providers[provider.provider_id] = provider
        if config is not None:
            self._configs[provider.provider_id] = config

    def get(self, provider_id: str) -> AIProvider | None:
        return self._providers.get(provider_id)

    def require(self, provider_id: str) -> AIProvider:
        provider = self.get(provider_id)
        if provider is None:
            raise KeyError(f"Unknown provider: {provider_id}")
        return provider

    def list_ids(self) -> list[str]:
        return sorted(self._providers.keys())

    def list_providers(self) -> list[AIProvider]:
        return [self._providers[k] for k in self.list_ids()]

    def get_config(self, provider_id: str) -> AIProviderConfig | None:
        return self._configs.get(provider_id)

    def enabled_by_priority(self) -> list[AIProvider]:
        items: list[tuple[int, str, AIProvider]] = []
        for provider_id, provider in self._providers.items():
            cfg = self._configs.get(provider_id)
            if cfg is not None and not cfg.enabled:
                continue
            priority = cfg.priority if cfg is not None else 999
            items.append((priority, provider_id, provider))
        items.sort(key=lambda x: (x[0], x[1]))
        return [p for _, _, p in items]

    def default_provider(self) -> AIProvider | None:
        for provider_id, cfg in self._configs.items():
            if cfg.is_default and cfg.enabled:
                return self._providers.get(provider_id)
        enabled = self.enabled_by_priority()
        return enabled[0] if enabled else None

    def providers_with_capability(
        self, capability: AICapability
    ) -> list[AIProvider]:
        return [
            p
            for p in self.enabled_by_priority()
            if p.supports(capability)
        ]

    def describe_all(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for provider in self.list_providers():
            row = provider.describe()
            cfg = self._configs.get(provider.provider_id)
            if cfg is not None:
                row["config"] = cfg.public_dict()
            rows.append(row)
        return rows

    def clear(self) -> None:
        self._providers.clear()
        self._configs.clear()


def build_default_registry(
    configs: list[AIProviderConfig] | None = None,
) -> AIProviderRegistry:
    """설정 기반 기본 Registry 구성."""

    registry = AIProviderRegistry()
    cfg_list = configs if configs is not None else load_provider_configs_from_settings()
    factories: dict[str, type] = {
        "mock": MockAIProvider,
        "openai": OpenAIProvider,
        "claude": ClaudeProvider,
        "gemini": GeminiProvider,
        "ollama": OllamaProvider,
        "openai_compatible": OpenAICompatibleProvider,
    }
    for cfg in cfg_list:
        factory = factories.get(cfg.provider_id)
        if factory is None:
            continue
        provider = factory(cfg)
        registry.register(provider, cfg)
    return registry
