"""STEP 11-1 — AI Provider Adapter Framework."""

from stock_platform.ai.providers.base import AIProvider
from stock_platform.ai.providers.capability import AICapability
from stock_platform.ai.providers.dto import (
    AIChatRequest,
    AIResponse,
    ChatMessage,
    ProviderHealth,
)
from stock_platform.ai.providers.manager import (
    AIManager,
    get_ai_manager,
    reset_ai_manager,
)
from stock_platform.ai.providers.mock_provider import MockAIProvider
from stock_platform.ai.providers.registry import (
    AIProviderRegistry,
    build_default_registry,
)

__all__ = [
    "AICapability",
    "AIChatRequest",
    "AIManager",
    "AIProvider",
    "AIProviderRegistry",
    "AIResponse",
    "ChatMessage",
    "MockAIProvider",
    "ProviderHealth",
    "build_default_registry",
    "get_ai_manager",
    "reset_ai_manager",
]
