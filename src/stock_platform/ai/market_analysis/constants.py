"""STEP 11-7 — Market/Chart analysis constants."""

from __future__ import annotations

ANALYSIS_TYPES = frozenset({"SYMBOL_CHART", "MARKET_OVERVIEW"})
TIMEFRAMES = frozenset({"1D", "1m", "3m", "5m", "15m"})
QUALITY_STATUSES = frozenset(
    {
        "GOOD",
        "ACCEPTABLE",
        "STALE",
        "INCOMPLETE",
        "GAP_DETECTED",
        "DUPLICATE_DETECTED",
        "INVALID",
        "UNKNOWN",
    }
)
ANALYSIS_STATUS = frozenset(
    {
        "DRAFT_ANALYSIS",
        "QUEUED",
        "RUNNING",
        "VALIDATED_ANALYSIS",
        "VALIDATED_WITH_WARNINGS",
        "BLOCKED",
        "INVALID",
        "FAILED",
        "CANCELLED",
        "SUPERSEDED",
    }
)

INDICATOR_VERSION = "indicator_engine_v1"
ANALYSIS_ENGINE_VERSION = "11.7.0"

MIN_DAILY_CANDLES = 30
MAX_DAILY_CANDLES = 250
MAX_MINUTE_CANDLES = 300
STALE_DAYS_KRX = 5
STALE_DAYS_UPBIT = 2

MAX_BATCH_MOCK = 100
MAX_BATCH_EXTERNAL = 10
HARD_BATCH_CAP = 100

MAX_SNAPSHOT_JSON_CHARS = 60_000
VISION_ENABLED_DEFAULT = False

REFERENCE_DISCLAIMER = (
    "AI 분석 결과는 참고용이며, 매수·매도 신호 또는 주문 지시가 아닙니다."
)

# Decimal → JSON 문자열 (float 금지)
DECIMAL_JSON_PLACES = 8
