"""Dual LLM research markets — hard isolation.

UPBIT CLEAN/RAG/Feedback 와 KIWOOM CLEAN/RAG/Feedback 를 절대 혼합하지 않는다.
"""

from __future__ import annotations

from typing import Any

MARKET_UPBIT = "UPBIT"
MARKET_KIWOOM = "KIWOOM"
VALID_MARKETS = frozenset({MARKET_UPBIT, MARKET_KIWOOM})


def normalize_market(value: object) -> str | None:
    raw = str(value or "").strip().upper()
    if raw in {"CRYPTO", "UPBIT"}:
        return MARKET_UPBIT
    if raw in {"KIWOOM", "KRX", "STOCK", "KOSPI", "KOSDAQ"}:
        return MARKET_KIWOOM
    if raw in VALID_MARKETS:
        return raw
    return None


def require_market(value: object) -> str:
    m = normalize_market(value)
    if m is None:
        raise ValueError(f"INVALID_MARKET:{value}")
    return m


def same_market(a: object, b: object) -> bool:
    na = normalize_market(a)
    nb = normalize_market(b)
    return na is not None and na == nb


def assert_market_match(*, current: object, historical: object) -> None:
    if not same_market(current, historical):
        raise AssertionError(
            f"CROSS_MARKET_FORBIDDEN current={current} historical={historical}"
        )


def market_of_payload(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("market", "research_market"):
        m = normalize_market(payload.get(key))
        if m:
            return m
    nested = payload.get("input_snapshot")
    if isinstance(nested, dict):
        return normalize_market(nested.get("market"))
    return None


__all__ = [
    "MARKET_UPBIT",
    "MARKET_KIWOOM",
    "VALID_MARKETS",
    "normalize_market",
    "require_market",
    "same_market",
    "assert_market_match",
    "market_of_payload",
]
