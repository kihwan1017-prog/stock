"""Market context research constants — cache / freshness / research-only flags."""

from __future__ import annotations

from datetime import timedelta

RESEARCH_ONLY = True
REAL_POLICY_BINDING = False
LLM_MAY_CREATE_ORDERS = False

# Cache TTLs
TTL_MARKET_SNAPSHOT = timedelta(minutes=5)
TTL_ASSET_METRICS = timedelta(minutes=5)
TTL_FEAR_GREED = timedelta(hours=1)
TTL_ASSET_DESCRIPTION = timedelta(days=7)
TTL_NEWS_INCREMENTAL = timedelta(minutes=15)

# Stale thresholds (as_of vs observed_at)
STALE_AFTER_MARKET = timedelta(minutes=15)
STALE_AFTER_ASSET = timedelta(minutes=15)
STALE_AFTER_FEAR_GREED = timedelta(hours=6)
STALE_AFTER_NEWS = timedelta(hours=24)
STALE_AFTER_DESCRIPTION = timedelta(days=14)

SCHEMA_MARKET = "operation"
TABLE_MARKET_CTX = "upbit_market_context_snapshot"
TABLE_ASSET_CTX = "upbit_asset_context_snapshot"
TABLE_LLM_ANALYSIS = "upbit_llm_context_analysis"
TABLE_ASSET_DESC = "upbit_asset_description_cache"

LLM_RECOMMENDATIONS = frozenset({"ALLOW", "HOLD", "REDUCE"})

RISK_FLAG_ENUM = frozenset(
    {
        "OVERHEATED",
        "SELL_PRESSURE",
        "RECENT_SPIKE",
        "MARKET_WEAK",
        "NEWS_NEGATIVE",
        "LOW_LIQUIDITY",
        "SECTOR_WEAK",
        "CONTEXT_UNAVAILABLE",
        "STALE_CONTEXT",
    }
)
