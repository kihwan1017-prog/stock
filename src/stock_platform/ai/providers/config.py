"""STEP 11-1 — Provider 설정 (env / Settings)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from stock_platform.ai.providers.security import mask_secret


@dataclass(slots=True)
class AIProviderConfig:
    provider_id: str
    enabled: bool = False
    priority: int = 100
    is_default: bool = False
    model: str = ""
    api_endpoint: str = ""
    api_key: str = ""
    timeout_seconds: float = 30.0
    retry_max: int = 2
    retry_backoff_seconds: float = 0.5
    max_tokens: int = 1024
    temperature: float = 0.2
    circuit_failure_threshold: int = 3
    circuit_reset_seconds: float = 30.0
    extra: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        """시크릿 마스킹된 공개 설정."""

        return {
            "provider_id": self.provider_id,
            "enabled": self.enabled,
            "priority": self.priority,
            "is_default": self.is_default,
            "model": self.model,
            "api_endpoint": self.api_endpoint,
            "api_key_configured": bool(self.api_key.strip()),
            "api_key_masked": mask_secret(self.api_key) if self.api_key else "",
            "timeout_seconds": self.timeout_seconds,
            "retry_max": self.retry_max,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "circuit_failure_threshold": self.circuit_failure_threshold,
            "circuit_reset_seconds": self.circuit_reset_seconds,
        }


def load_provider_configs_from_settings() -> list[AIProviderConfig]:
    """Settings / env 기반 Provider 설정 로드."""

    from stock_platform.common.settings import get_settings

    settings = get_settings()

    mock_enabled = bool(
        getattr(settings, "ai_provider_mock_enabled", True)
    )
    mock_default = bool(
        getattr(settings, "ai_provider_mock_default", True)
    )

    configs = [
        AIProviderConfig(
            provider_id="mock",
            enabled=mock_enabled,
            priority=int(getattr(settings, "ai_provider_mock_priority", 10)),
            is_default=mock_default,
            model=str(getattr(settings, "ai_provider_mock_model", "mock-v1")),
            timeout_seconds=float(
                getattr(settings, "ai_provider_mock_timeout_seconds", 5.0)
            ),
            retry_max=int(getattr(settings, "ai_provider_mock_retry_max", 1)),
            extra={
                "fixed_signal": getattr(
                    settings, "ai_provider_mock_signal", "HOLD"
                ),
                "latency_ms": float(
                    getattr(settings, "ai_provider_mock_latency_ms", 5.0)
                ),
                "simulate_error": bool(
                    getattr(settings, "ai_provider_mock_simulate_error", False)
                ),
                "simulate_timeout": bool(
                    getattr(
                        settings, "ai_provider_mock_simulate_timeout", False
                    )
                ),
            },
        ),
        AIProviderConfig(
            provider_id="openai",
            enabled=bool(getattr(settings, "ai_provider_openai_enabled", False)),
            priority=int(getattr(settings, "ai_provider_openai_priority", 20)),
            is_default=False,
            model=str(
                getattr(settings, "ai_provider_openai_model", "gpt-4o-mini")
            ),
            api_endpoint=str(
                getattr(
                    settings,
                    "ai_provider_openai_endpoint",
                    "https://api.openai.com/v1",
                )
            ),
            api_key=str(getattr(settings, "ai_provider_openai_api_key", "")),
            timeout_seconds=float(
                getattr(settings, "ai_provider_openai_timeout_seconds", 30.0)
            ),
            retry_max=int(getattr(settings, "ai_provider_openai_retry_max", 2)),
            max_tokens=int(
                getattr(settings, "ai_provider_openai_max_tokens", 1024)
            ),
            temperature=float(
                getattr(settings, "ai_provider_openai_temperature", 0.2)
            ),
        ),
        AIProviderConfig(
            provider_id="claude",
            enabled=bool(getattr(settings, "ai_provider_claude_enabled", False)),
            priority=int(getattr(settings, "ai_provider_claude_priority", 30)),
            model=str(
                getattr(
                    settings,
                    "ai_provider_claude_model",
                    "claude-3-5-sonnet-latest",
                )
            ),
            api_endpoint=str(
                getattr(
                    settings,
                    "ai_provider_claude_endpoint",
                    "https://api.anthropic.com",
                )
            ),
            api_key=str(getattr(settings, "ai_provider_claude_api_key", "")),
            timeout_seconds=float(
                getattr(settings, "ai_provider_claude_timeout_seconds", 30.0)
            ),
        ),
        AIProviderConfig(
            provider_id="gemini",
            enabled=bool(getattr(settings, "ai_provider_gemini_enabled", False)),
            priority=int(getattr(settings, "ai_provider_gemini_priority", 40)),
            model=str(
                getattr(settings, "ai_provider_gemini_model", "gemini-2.0-flash")
            ),
            api_endpoint=str(
                getattr(
                    settings,
                    "ai_provider_gemini_endpoint",
                    "https://generativelanguage.googleapis.com",
                )
            ),
            api_key=str(getattr(settings, "ai_provider_gemini_api_key", "")),
            timeout_seconds=float(
                getattr(settings, "ai_provider_gemini_timeout_seconds", 30.0)
            ),
        ),
        AIProviderConfig(
            provider_id="ollama",
            enabled=bool(
                getattr(settings, "ai_provider_ollama_enabled", False)
            ),
            priority=int(getattr(settings, "ai_provider_ollama_priority", 50)),
            model=str(
                getattr(
                    settings,
                    "ai_provider_ollama_model",
                    getattr(settings, "ollama_model", "qwen3.5:4b"),
                )
            ),
            api_endpoint=str(
                getattr(
                    settings,
                    "ai_provider_ollama_endpoint",
                    getattr(settings, "ollama_base_url", "http://127.0.0.1:11434"),
                )
            ),
            timeout_seconds=float(
                getattr(
                    settings,
                    "ai_provider_ollama_timeout_seconds",
                    getattr(settings, "ollama_timeout_seconds", 120.0),
                )
            ),
        ),
        AIProviderConfig(
            provider_id="openai_compatible",
            enabled=bool(
                getattr(
                    settings, "ai_provider_openai_compatible_enabled", False
                )
            ),
            priority=int(
                getattr(settings, "ai_provider_openai_compatible_priority", 60)
            ),
            model=str(
                getattr(
                    settings, "ai_provider_openai_compatible_model", "local-model"
                )
            ),
            api_endpoint=str(
                getattr(
                    settings, "ai_provider_openai_compatible_endpoint", ""
                )
            ),
            api_key=str(
                getattr(settings, "ai_provider_openai_compatible_api_key", "")
            ),
            timeout_seconds=float(
                getattr(
                    settings,
                    "ai_provider_openai_compatible_timeout_seconds",
                    30.0,
                )
            ),
        ),
    ]
    return configs
