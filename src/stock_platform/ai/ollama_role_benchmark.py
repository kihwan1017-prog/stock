"""Ollama role benchmark helpers — re-export runner entry for reuse."""

from __future__ import annotations

# Thin package marker so future suites can import fixtures from .run script
# or call OllamaClient with role-resolved model names.
__all__ = ["ROLE_ANALYSIS", "ROLE_TRADING"]

ROLE_ANALYSIS = "ANALYSIS_LLM"
ROLE_TRADING = "TRADING_LLM"
