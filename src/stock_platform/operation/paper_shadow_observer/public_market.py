"""Upbit 공개 시세만 조회. credential/private/order 없음."""

from __future__ import annotations

from typing import Any

import httpx

UPBIT_PUBLIC_BASE = "https://api.upbit.com"
PUBLIC_TICKER_PATH = "/v1/ticker"
PUBLIC_MARKET_PATH = "/v1/market/all"


def fetch_krw_markets(*, timeout_seconds: float = 10.0) -> list[str]:
    """KRW 마켓 코드만. 인증 헤더 없음."""

    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.get(
            f"{UPBIT_PUBLIC_BASE}{PUBLIC_MARKET_PATH}",
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        rows = response.json()
    out: list[str] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        market = str(row.get("market") or "")
        if market.startswith("KRW-"):
            out.append(market)
    return out


def fetch_public_tickers(
    markets: list[str],
    *,
    timeout_seconds: float = 15.0,
) -> list[dict[str, Any]]:
    """공개 /v1/ticker. side-effect-free GET."""

    if not markets:
        return []
    chunk = markets[:100]
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.get(
            f"{UPBIT_PUBLIC_BASE}{PUBLIC_TICKER_PATH}",
            params={"markets": ",".join(chunk)},
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        rows = response.json()
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]
