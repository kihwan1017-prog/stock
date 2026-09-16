"""Paper Shadow 상수 — TradingOrder와 분리된 가상 추적."""

from __future__ import annotations

SHADOW_STATUS_ACTIVE = "ACTIVE"
SHADOW_STATUS_COMPLETED = "COMPLETED"
SHADOW_STATUS_CANCELLED = "CANCELLED"

SHADOW_RECOMMENDATIONS = frozenset({"ALLOW", "REDUCE"})

# 평가 창 (분) — 확장 가능
EVALUATION_WINDOWS_MINUTES: tuple[int, ...] = (5, 15, 30, 60)

# 메타데이터 기반 스테이블 베이스 자산 (심볼 하드코딩 금지 — base asset 카테고리)
# english_name 키워드와 함께 policy에서 사용
DEFAULT_STABLECOIN_BASE_ASSETS: frozenset[str] = frozenset(
    {
        "USDT",
        "USDC",
        "USD1",
        "DAI",
        "BUSD",
        "TUSD",
        "USDP",
        "FDUSD",
        "USDE",
        "USDS",
        "USDD",
    }
)

STABLECOIN_NAME_KEYWORDS: tuple[str, ...] = (
    "tether",
    "usd coin",
    "usdcoin",
    "trueusd",
    "binance usd",
    "first digital usd",
    "paypal usd",
    "world liberty financial usd",
)
