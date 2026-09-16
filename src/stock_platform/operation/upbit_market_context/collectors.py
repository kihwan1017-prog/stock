"""Collectors — official ticker metrics + third-party fear/greed (no DataLab scrape)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from stock_platform.operation.upbit_market_context.constants import (
    STALE_AFTER_FEAR_GREED,
    STALE_AFTER_MARKET,
)
from stock_platform.operation.upbit_market_context.source_registry import (
    QUALITY_AVAILABLE,
    QUALITY_INVALID,
    QUALITY_MISSING,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def fetch_fear_greed_alternative_me(
    *,
    client: httpx.Client | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Alternative.me FNG — research provenance."""

    owns = client is None
    http = client or httpx.Client(timeout=timeout)
    try:
        resp = http.get("https://api.alternative.me/fng/", params={"limit": 1})
        resp.raise_for_status()
        payload = resp.json()
        data = (payload.get("data") or [None])[0]
        if not isinstance(data, dict):
            return {
                "feature_key": "fear_greed",
                "quality": QUALITY_INVALID,
                "value_json": {},
                "source": "alternative_me_fear_greed",
                "source_timestamp": _now(),
                "stale_after": _now() + STALE_AFTER_FEAR_GREED,
                "raw_provenance": {"error": "EMPTY_DATA"},
            }
        ts = datetime.fromtimestamp(int(data["timestamp"]), tz=timezone.utc)
        return {
            "feature_key": "fear_greed",
            "quality": QUALITY_AVAILABLE,
            "value_json": {
                "value": int(data.get("value")),
                "classification": data.get("value_classification"),
            },
            "source": "alternative_me_fear_greed",
            "source_timestamp": ts,
            "observed_at": _now(),
            "stale_after": _now() + STALE_AFTER_FEAR_GREED,
            "raw_provenance": {"endpoint": "https://api.alternative.me/fng/", "raw": data},
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "feature_key": "fear_greed",
            "quality": QUALITY_MISSING,
            "value_json": {},
            "source": "alternative_me_fear_greed",
            "source_timestamp": _now(),
            "observed_at": _now(),
            "stale_after": _now() + STALE_AFTER_FEAR_GREED,
            "raw_provenance": {"error": str(exc)[:160]},
        }
    finally:
        if owns:
            http.close()


def build_market_metrics_from_tickers(
    tickers: list[dict[str, Any]],
    *,
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Upbit /v1/ticker 배치 → market + per-asset features (lookahead 없음)."""

    now = observed_at or _now()
    krw = [
        t
        for t in tickers
        if str(t.get("market") or "").startswith("KRW-")
    ]
    if not krw:
        return [
            {
                "feature_key": "market_breadth",
                "quality": QUALITY_MISSING,
                "value_json": {},
                "source": "upbit_quotation_ticker",
                "source_timestamp": now,
                "observed_at": now,
                "stale_after": now + STALE_AFTER_MARKET,
                "symbol": None,
                "raw_provenance": {"error": "NO_KRW_TICKERS"},
            }
        ]

    advancing = 0
    declining = 0
    total_turnover = 0.0
    for t in krw:
        chg = float(t.get("signed_change_rate") or 0)
        if chg > 0:
            advancing += 1
        elif chg < 0:
            declining += 1
        total_turnover += float(t.get("acc_trade_price_24h") or 0)

    n = len(krw)
    adv_ratio = advancing / n if n else None
    market_rows: list[dict[str, Any]] = [
        {
            "feature_key": "advancing_asset_ratio",
            "quality": QUALITY_AVAILABLE,
            "value_json": {
                "advancing": advancing,
                "declining": declining,
                "unchanged": n - advancing - declining,
                "ratio": round(adv_ratio, 6) if adv_ratio is not None else None,
                "n": n,
            },
            "source": "upbit_quotation_ticker",
            "source_timestamp": now,
            "observed_at": now,
            "stale_after": now + STALE_AFTER_MARKET,
            "symbol": None,
            "raw_provenance": {"markets": n},
        },
        {
            "feature_key": "24h_turnover",
            "quality": QUALITY_AVAILABLE,
            "value_json": {"total_acc_trade_price_24h_krw": round(total_turnover, 2)},
            "source": "upbit_quotation_ticker",
            "source_timestamp": now,
            "observed_at": now,
            "stale_after": now + STALE_AFTER_MARKET,
            "symbol": None,
            "raw_provenance": {"markets": n},
        },
        {
            "feature_key": "market_return",
            "quality": QUALITY_AVAILABLE,
            "value_json": {
                "median_signed_change_rate": _median(
                    [float(t.get("signed_change_rate") or 0) for t in krw]
                ),
                "note": "proxy from KRW ticker signed_change_rate median",
            },
            "source": "upbit_quotation_ticker",
            "source_timestamp": now,
            "observed_at": now,
            "stale_after": now + STALE_AFTER_MARKET,
            "symbol": None,
            "raw_provenance": {"markets": n},
        },
    ]

    # turnover rank
    ranked = sorted(
        krw,
        key=lambda t: float(t.get("acc_trade_price_24h") or 0),
        reverse=True,
    )
    for idx, t in enumerate(ranked, start=1):
        sym = str(t.get("market"))
        market_rows.append(
            {
                "feature_key": "asset_ticker_bundle",
                "quality": QUALITY_AVAILABLE,
                "symbol": sym,
                "value_json": {
                    "trade_price": t.get("trade_price"),
                    "signed_change_rate": t.get("signed_change_rate"),
                    "acc_trade_price_24h": t.get("acc_trade_price_24h"),
                    "turnover_rank": idx,
                    "high_price": t.get("high_price"),
                    "low_price": t.get("low_price"),
                    "prev_closing_price": t.get("prev_closing_price"),
                },
                "source": "upbit_quotation_ticker",
                "source_timestamp": now,
                "observed_at": now,
                "stale_after": now + STALE_AFTER_MARKET,
                "raw_provenance": {"market": sym},
            }
        )
    return market_rows


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    mid = len(s) // 2
    if len(s) % 2:
        return round(s[mid], 8)
    return round((s[mid - 1] + s[mid]) / 2, 8)


def blocked_datalab_placeholder(feature_key: str) -> dict[str, Any]:
    now = _now()
    return {
        "feature_key": feature_key,
        "quality": "BLOCKED_BY_ROBOTS",
        "value_json": {},
        "source": "upbit_datalab_indices",
        "source_timestamp": now,
        "observed_at": now,
        "stale_after": None,
        "symbol": None,
        "raw_provenance": {
            "robots": "Disallow: /api/",
            "decision": "NO_SCRAPE",
        },
    }


def dedupe_news_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """headline+published_at 기준 중복 제거."""

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        key = f"{it.get('headline')}|{it.get('published_at')}|{it.get('source')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
