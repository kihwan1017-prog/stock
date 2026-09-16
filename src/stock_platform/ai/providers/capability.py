"""STEP 11-1 — AI Provider Capability 선언."""

from __future__ import annotations

from enum import StrEnum


class AICapability(StrEnum):
    CHAT = "CHAT"
    NEWS = "NEWS"
    VISION = "VISION"
    TOOLS = "TOOLS"
    EMBEDDING = "EMBEDDING"
    JSON = "JSON"
    STREAM = "STREAM"
    FUNCTION_CALL = "FUNCTION_CALL"
    STRATEGY = "STRATEGY"
    CHART = "CHART"
    SUMMARIZE = "SUMMARIZE"
