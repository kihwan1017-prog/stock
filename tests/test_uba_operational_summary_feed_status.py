"""uba_operational_summary market_feed status mapping."""

from __future__ import annotations

from stock_platform.trading.uba_operational_summary import (
    _map_market_feed_status,
)


def test_market_feed_maps_ok_true_to_real_fresh() -> None:
    assert (
        _map_market_feed_status(
            {
                "ok": True,
                "reason": "OK",
                "quote_ws": {"connected": True, "running": True},
            }
        )
        == "REAL_FRESH"
    )


def test_market_feed_maps_stale_reason() -> None:
    assert (
        _map_market_feed_status({"ok": False, "reason": "QUOTE_STALE"})
        == "REAL_STALE"
    )


def test_market_feed_maps_disconnected() -> None:
    assert (
        _map_market_feed_status(
            {"ok": False, "quote_ws": {"connected": False}}
        )
        == "DISCONNECTED"
    )


def test_legacy_healthy_key_still_works() -> None:
    assert _map_market_feed_status({"healthy": True, "stale": False}) == (
        "REAL_FRESH"
    )
