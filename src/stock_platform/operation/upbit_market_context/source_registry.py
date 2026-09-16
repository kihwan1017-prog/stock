"""Upbit Market Context LLM Research — source registry (audit SoT).

DataLab robots.txt: Disallow /api/ → DataLab HTTP API scraping 금지.
REAL 주문/정책과 무관 — research only.
"""

from __future__ import annotations

from typing import Any

# ── Quality codes ──────────────────────────────────────────────────────────
QUALITY_AVAILABLE = "AVAILABLE"
QUALITY_STALE = "STALE"
QUALITY_MISSING = "MISSING"
QUALITY_INVALID = "INVALID"
QUALITY_BLOCKED = "BLOCKED_BY_ROBOTS"

METHOD_OFFICIAL_API = "OFFICIAL_API"
METHOD_DERIVED_OFFICIAL = "DERIVED_FROM_OFFICIAL"
METHOD_THIRD_PARTY_API = "THIRD_PARTY_PUBLIC_API"
METHOD_EXISTING_PIPELINE = "EXISTING_PIPELINE"
METHOD_WEB_ONLY_DEFERRED = "WEB_ONLY_DEFERRED"
METHOD_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

AVAILABLE_SOURCE_LIST: list[dict[str, Any]] = [
    {
        "id": "upbit_quotation_ticker",
        "name": "Upbit Quotation Ticker / Candles / Markets",
        "method": METHOD_OFFICIAL_API,
        "endpoint": "https://api.upbit.com/v1/{ticker,candles,market/all}",
        "auth": False,
        "provides": [
            "24h_turnover",
            "daily_return",
            "1h_return",
            "weekly_return_proxy",
            "advancing_asset_ratio",
            "turnover_rank",
            "market_warning",
            "instrument_name",
        ],
        "status": "IMPLEMENTED",
    },
    {
        "id": "upbit_notice_api_manager",
        "name": "Upbit Announcements (api-manager)",
        "method": METHOD_OFFICIAL_API,
        "endpoint": "https://api-manager.upbit.com/api/v1/announcements",
        "auth": False,
        "provides": ["news_notice", "listing_delisting"],
        "status": "IMPLEMENTED_EXISTING",
        "reuse": "news.upbit_notice_client / news_article",
    },
    {
        "id": "naver_crypto_news",
        "name": "Naver crypto news (optional collector)",
        "method": METHOD_EXISTING_PIPELINE,
        "endpoint": "existing crypto_news_collector",
        "auth": "API key if enabled",
        "provides": ["headline", "published_at", "related_symbols"],
        "status": "IMPLEMENTED_EXISTING",
        "reuse": "news.news_article / news_ai_analysis",
    },
    {
        "id": "alternative_me_fear_greed",
        "name": "Alternative.me Crypto Fear & Greed",
        "method": METHOD_THIRD_PARTY_API,
        "endpoint": "https://api.alternative.me/fng/",
        "auth": False,
        "provides": ["fear_greed"],
        "status": "IMPLEMENTED",
        "note": "Not Upbit-native; provenance stamped. Research only.",
    },
    {
        "id": "upbit_datalab_indices",
        "name": "Upbit DataLab (UBMI/UBAI/Upbit10/30/F&G/Season)",
        "method": METHOD_WEB_ONLY_DEFERRED,
        "endpoint": "https://datalab.upbit.com/",
        "auth": "unknown",
        "robots": "Disallow: /api/ — scraping blocked",
        "provides": [
            "upbit_market_index",
            "altcoin_index",
            "upbit10",
            "upbit30",
            "datalab_fear_greed",
            "altcoin_season",
            "btc_dominance_datalab",
            "buy_execution_strength_rank",
            "sell_execution_strength_rank",
            "asset_description_doc",
        ],
        "status": "DEFERRED_NO_SCRAPE",
    },
    {
        "id": "execution_strength_proxy",
        "name": "Buy/Sell pressure proxy from orderbook/trades",
        "method": METHOD_DERIVED_OFFICIAL,
        "endpoint": "orderbook + optional trade ticks",
        "auth": False,
        "provides": ["buy_sell_pressure_ratio"],
        "status": "PARTIAL",
        "note": "Rank board from DataLab deferred; local proxy optional",
    },
]


OFFICIAL_API_AVAILABLE = [
    s for s in AVAILABLE_SOURCE_LIST if s["method"] == METHOD_OFFICIAL_API
]
WEB_ONLY_SOURCES = [
    s for s in AVAILABLE_SOURCE_LIST if s["method"] == METHOD_WEB_ONLY_DEFERRED
]
THIRD_PARTY_SOURCES = [
    s for s in AVAILABLE_SOURCE_LIST if s["method"] == METHOD_THIRD_PARTY_API
]

# Feature → collection method map for reports
FEATURE_SOURCE_MAP: dict[str, dict[str, Any]] = {
    "upbit_market_index": {"source": "upbit_datalab_indices", "quality_default": QUALITY_BLOCKED},
    "altcoin_index": {"source": "upbit_datalab_indices", "quality_default": QUALITY_BLOCKED},
    "upbit10": {"source": "upbit_datalab_indices", "quality_default": QUALITY_BLOCKED},
    "upbit30": {"source": "upbit_datalab_indices", "quality_default": QUALITY_BLOCKED},
    "btc_dominance": {"source": "upbit_datalab_indices", "quality_default": QUALITY_MISSING},
    "altcoin_season": {"source": "upbit_datalab_indices", "quality_default": QUALITY_BLOCKED},
    "fear_greed": {"source": "alternative_me_fear_greed", "quality_default": QUALITY_AVAILABLE},
    "market_return": {"source": "upbit_quotation_ticker", "quality_default": QUALITY_AVAILABLE},
    "advancing_asset_ratio": {
        "source": "upbit_quotation_ticker",
        "quality_default": QUALITY_AVAILABLE,
    },
    "24h_turnover": {"source": "upbit_quotation_ticker", "quality_default": QUALITY_AVAILABLE},
    "daily_return": {"source": "upbit_quotation_ticker", "quality_default": QUALITY_AVAILABLE},
    "weekly_return": {"source": "upbit_quotation_ticker", "quality_default": QUALITY_AVAILABLE},
    "1h_return": {"source": "upbit_quotation_ticker", "quality_default": QUALITY_AVAILABLE},
    "turnover_rank": {"source": "upbit_quotation_ticker", "quality_default": QUALITY_AVAILABLE},
    "buy_execution_strength_rank": {
        "source": "upbit_datalab_indices",
        "quality_default": QUALITY_BLOCKED,
    },
    "sell_execution_strength_rank": {
        "source": "upbit_datalab_indices",
        "quality_default": QUALITY_BLOCKED,
    },
    "buy_sell_pressure_ratio": {
        "source": "execution_strength_proxy",
        "quality_default": QUALITY_MISSING,
    },
    "news": {"source": "upbit_notice_api_manager", "quality_default": QUALITY_AVAILABLE},
    "asset_description": {
        "source": "upbit_datalab_indices",
        "quality_default": QUALITY_MISSING,
        "fallback": "instrument.extra_data / market_event",
    },
}


def source_audit_report() -> dict[str, Any]:
    return {
        "AVAILABLE_SOURCE_LIST": AVAILABLE_SOURCE_LIST,
        "OFFICIAL_API_AVAILABLE": [s["id"] for s in OFFICIAL_API_AVAILABLE],
        "WEB_ONLY_SOURCES": [s["id"] for s in WEB_ONLY_SOURCES],
        "THIRD_PARTY_SOURCES": [s["id"] for s in THIRD_PARTY_SOURCES],
        "DATA_COLLECTION_METHOD": {
            "official_first": True,
            "datalab_scrape": False,
            "datalab_robots_disallow_api": True,
            "reuse_news_pipeline": True,
            "no_html_scraping": True,
        },
        "FEATURE_SOURCE_MAP": FEATURE_SOURCE_MAP,
    }
