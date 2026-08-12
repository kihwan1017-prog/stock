"""Ollama format grammar용 축소 CHART schema.

전체 CHART_ANALYSIS_RESULT_V1은 일부 Ollama 버전에서 format BAD_REQUEST.
Provider format 제약은 축소 schema, 앱 검증은 기존 전체 schema를 유지한다.
"""

from __future__ import annotations

from typing import Any

OLLAMA_CHART_FORMAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "task_type",
        "confidence",
        "reasoning_summary",
        "result",
    ],
    "properties": {
        "schema_version": {"type": "string", "enum": ["1.0"]},
        "task_type": {"type": "string", "enum": ["CHART_ANALYSIS"]},
        "confidence": {"type": "number"},
        "reasoning_summary": {"type": "string"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "citations": {"type": "array"},
        "result": {
            "type": "object",
            "additionalProperties": True,
            "required": ["trend", "momentum", "volatility", "summary"],
            "properties": {
                "trend": {
                    "type": "string",
                    "enum": [
                        "STRONG_DOWNTREND",
                        "DOWNTREND",
                        "SIDEWAYS",
                        "UPTREND",
                        "STRONG_UPTREND",
                        "UNCERTAIN",
                        "UP",
                        "DOWN",
                        "UNKNOWN",
                    ],
                },
                "momentum": {
                    "type": "string",
                    "enum": ["BEARISH", "NEUTRAL", "BULLISH", "UNKNOWN"],
                },
                "volatility": {
                    "type": "string",
                    "enum": [
                        "VERY_LOW",
                        "LOW",
                        "NORMAL",
                        "HIGH",
                        "VERY_HIGH",
                        "UNKNOWN",
                    ],
                },
                "summary": {"type": "string"},
                "trend_strength": {"type": "string"},
                "volume_condition": {"type": "string"},
                "support_levels": {"type": "array"},
                "resistance_levels": {"type": "array"},
                "notable_patterns": {"type": "array"},
                "indicator_interpretations": {"type": "array"},
                "bullish_factors": {"type": "array"},
                "bearish_factors": {"type": "array"},
                "uncertainty_factors": {"type": "array"},
                "indicators_used": {"type": "array"},
            },
        },
    },
}
