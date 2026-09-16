"""STEP 12-2-2 — Generation Run 상태/한도/화이트리스트."""

from __future__ import annotations

GENERATION_RUN_STATUS = frozenset(
    {
        "PENDING",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT",
    }
)

TERMINAL_GENERATION_RUN_STATUSES = frozenset(
    {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}
)

# 상태 전이표 — 종결 상태에서는 어떤 전이도 허용하지 않는다(역행/재실행 금지).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"RUNNING", "CANCELLED"}),
    "RUNNING": frozenset({"SUCCEEDED", "FAILED", "TIMED_OUT"}),
    "SUCCEEDED": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
    "TIMED_OUT": frozenset(),
}

TASK_TYPE = "STRATEGY_DRAFT"
PROMPT_TEMPLATE_CODE = "strategy_draft_generation_v1"
OUTPUT_SCHEMA_CODE = "strategy_draft_generation_output_v1"

# STEP12-2-3A: 실 Ollama(qwen3.5:4b) 검증 결과 temperature=0.2/max_tokens=2000
# 조합에서는 구조화 스키마(중첩 규칙 포함)를 다 채우기 전에 토큰 예산을
# 소진해 필수 필드 누락으로 실패하는 사례가 재현됐다. temperature를 낮추고
# (이 태스크는 창의적 글쓰기가 아니라 구조화된 초안 생성이라 낮은 값이
# 적합) max_tokens를 늘려 실측으로 성공을 확인했다.
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 4000

# Structured Output 화이트리스트 — 안전 검증(STEP12-2-2 §8)에서 사용.
ALLOWED_MARKET_TYPES = frozenset({"KR_STOCK", "CRYPTO"})
ALLOWED_TIMEFRAMES = frozenset(
    {"1m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"}
)
ALLOWED_INDICATORS = frozenset(
    {
        "SMA", "EMA", "RSI", "MACD", "BOLLINGER_BAND", "ATR", "STOCHASTIC",
        "VOLUME", "OBV", "ADX", "CCI", "VWAP",
    }
)
ALLOWED_OPERATORS = frozenset(
    {"GT", "GTE", "LT", "LTE", "EQ", "CROSS_ABOVE", "CROSS_BELOW"}
)
ALLOWED_STOP_LOSS_TYPES = frozenset({"PERCENT", "ATR_MULTIPLE"})
ALLOWED_TAKE_PROFIT_TYPES = frozenset({"PERCENT", "RR_RATIO"})
ALLOWED_POSITION_SIZING_METHODS = frozenset(
    {"FIXED_PERCENT", "KELLY_FRACTION", "FIXED_UNITS"}
)

# 안전 상한 — 이 범위를 벗어나면 AI 응답이라도 차단한다.
MAX_STOP_LOSS_PERCENT = 30.0
MAX_TAKE_PROFIT_PERCENT = 200.0
MAX_POSITION_SIZE_PERCENT = 1.0  # FIXED_PERCENT/KELLY_FRACTION은 0~1(비율)
MAX_RULES_PER_SIDE = 10
MAX_SYMBOLS = 20
MAX_STRING_FIELD_CHARS = 2000
