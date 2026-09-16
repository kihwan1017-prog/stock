"""News Intelligence Shadow — constants / policy (REAL unchanged)."""

from __future__ import annotations

PIPELINE_VERSION = "news_intelligence_pipeline_v1"
SHADOW_POLICY_VERSION = "news_intelligence_shadow_v1"

DECISION_ALERT = "ALERT_CRITICAL"
DECISION_OBSERVE = "OBSERVE"
DECISION_IGNORE = "IGNORE"

MARKET_UPBIT = "UPBIT"
MARKET_KIWOOM = "KIWOOM"

SOURCE_UPBIT_NOTICE = "UPBIT_NOTICE"
SOURCE_CRYPTO_NEWS = "CRYPTO_NEWS"
SOURCE_NAVER = "NAVER"
SOURCE_DART = "DART"

# Upbit notice categories that warrant informational Telegram
UPBIT_CRITICAL_NOTICE_CATEGORIES = frozenset(
    {
        "CAUTION",
        "DELISTING",
        "DEPOSIT_WITHDRAWAL",
    }
)
