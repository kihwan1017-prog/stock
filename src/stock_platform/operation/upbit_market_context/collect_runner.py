"""Upbit market/asset context 1회 수집 실행기 — research only.

Scheduler · collect-once API 공용. REAL 주문/정책과 무관.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_market_context.as_of import as_utc
from stock_platform.operation.upbit_market_context.constants import (
    TTL_ASSET_DESCRIPTION,
)
from stock_platform.operation.upbit_market_context.entities import (
    UpbitAssetDescriptionCacheEntity,
)
from stock_platform.operation.upbit_market_context.snapshot_service import (
    MarketContextSnapshotService,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def fetch_krw_tickers(
    *, timeout: float = 20.0
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Upbit 공식 market/all + ticker 배치. (markets_meta, tickers)"""

    tickers: list[dict[str, Any]] = []
    with httpx.Client(timeout=timeout) as http:
        markets_resp = http.get(
            "https://api.upbit.com/v1/market/all",
            params={"isDetails": "true"},
        )
        markets_resp.raise_for_status()
        market_rows = [m for m in markets_resp.json() if isinstance(m, dict)]
        markets = [
            str(m["market"])
            for m in market_rows
            if str(m.get("market", "")).startswith("KRW-")
        ]
        for i in range(0, len(markets), 100):
            chunk = markets[i : i + 100]
            tr = http.get(
                "https://api.upbit.com/v1/ticker",
                params={"markets": ",".join(chunk)},
            )
            tr.raise_for_status()
            tickers.extend([x for x in tr.json() if isinstance(x, dict)])
    return market_rows, tickers


def _description_needs_refresh(session: Session, symbol: str) -> bool:
    existing = session.scalar(
        select(UpbitAssetDescriptionCacheEntity).where(
            UpbitAssetDescriptionCacheEntity.symbol == symbol
        )
    )
    if existing is None or existing.refreshed_at is None:
        return True
    refreshed = as_utc(existing.refreshed_at)
    if refreshed is None:
        return True
    return (_now() - refreshed) >= TTL_ASSET_DESCRIPTION


def run_market_context_collect(
    session: Session,
    *,
    include_fear_greed: bool = True,
    description_limit: int | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """KRW 전종목 ticker → market/asset snapshot 저장.

    description_limit:
      None → KRW 전종목 stub (TTL 캐시로 실제 갱신은 드묾)
      int → 상위 N개만 (collect-once dry용)
    """

    market_rows, tickers = fetch_krw_tickers(timeout=timeout)
    svc = MarketContextSnapshotService(session)
    by_m = {str(m.get("market")): m for m in market_rows}
    krw_symbols = [
        str(m.get("market"))
        for m in market_rows
        if str(m.get("market", "")).startswith("KRW-")
    ]
    targets = (
        krw_symbols
        if description_limit is None
        else krw_symbols[: max(0, int(description_limit))]
    )
    desc_upserted = 0
    desc_skipped_ttl = 0
    for sym in targets:
        if not _description_needs_refresh(session, sym):
            desc_skipped_ttl += 1
            continue
        meta = by_m.get(sym) or {}
        event = meta.get("market_event")
        svc.upsert_description_stub(
            symbol=sym,
            korean_name=meta.get("korean_name"),
            english_name=meta.get("english_name"),
            market_warning=event if isinstance(event, dict) else None,
        )
        desc_upserted += 1

    result = svc.collect_and_persist_from_tickers(
        tickers, include_fear_greed=include_fear_greed
    )
    return {
        "ok": True,
        "result": result,
        "ticker_count": len(tickers),
        "krw_symbol_count": len(krw_symbols),
        "description_upserted": desc_upserted,
        "description_skipped_ttl": desc_skipped_ttl,
        "include_fear_greed": include_fear_greed,
        "live_order": False,
        "REAL_POLICY_CHANGED": "NO",
        "datalab_scrape": False,
    }
