from __future__ import annotations

from stock_platform.common.settings import (
    get_settings,
)
from stock_platform.performance.selector_llm import (
    OllamaStrategySelectorClient,
)


def build_strategy_selector_llm():
    settings = get_settings()

    return OllamaStrategySelectorClient(
        base_url=settings.ollama_base_url,
        model_name=settings.ollama_model,
        timeout_seconds=120.0,
    )
