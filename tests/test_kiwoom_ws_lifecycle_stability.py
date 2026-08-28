"""KIWOOM WS lifecycle stability — warmup grace, generation race, single owner."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.trading.kiwoom_feed_recovery import (
    FEED_WARMUP_GRACE_SECONDS,
    ensure_kiwoom_feed_fresh,
    kiwoom_feed_in_warmup_grace,
)


def test_warmup_grace_constants() -> None:
    assert FEED_WARMUP_GRACE_SECONDS >= 60.0


def test_warmup_grace_recent_task() -> None:
    assert kiwoom_feed_in_warmup_grace(
        {
            "running": True,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def test_warmup_grace_expired_task() -> None:
    old = (datetime.now(timezone.utc) - timedelta(seconds=FEED_WARMUP_GRACE_SECONDS + 5)).isoformat()
    assert not kiwoom_feed_in_warmup_grace(
        {"running": True, "started_at": old}
    )


@pytest.mark.asyncio
async def test_ensure_skips_hard_reconnect_during_warmup() -> None:
    session = MagicMock()
    runtime = MagicMock()
    runtime.status.return_value = {
        "running": True,
        "connected": True,
        "user_broker_account_id": 1381,
        "feed_age_seconds": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "client": {"event_count": 0},
    }
    runtime.start = AsyncMock(return_value={"started": True, "connected": True})

    health = {
        "components": {"feed": "CONNECTING"},
        "feed_detail": {"reason": "NO_REAL_TICK_YET"},
        "heartbeats": {},
    }

    with patch(
        "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime",
        runtime,
    ):
        out = await ensure_kiwoom_feed_fresh(
            session,
            user_broker_account_id=1381,
            symbols=["034310"],
            actor="TEST",
            health_snapshot=health,
        )

    runtime.stop.assert_not_called()
    assert out.get("hard_reconnect") is False
    assert out.get("warmup_grace") is True


@pytest.mark.asyncio
async def test_stop_does_not_clear_newer_generation() -> None:
    from stock_platform.realtime.kiwoom_market_realtime_runtime import (
        KiwoomMarketRealtimeRuntime,
    )

    rt = KiwoomMarketRealtimeRuntime()
    rt._generation = 1
    client = MagicMock()
    client.shutdown = AsyncMock()
    client.note_exit_reason = MagicMock()
    rt._client = client
    rt._task = None
    rt._uba_id = 1381
    rt._started_at = datetime.now(timezone.utc)

    async def _bump_generation() -> None:
        rt._generation = 2

    client.shutdown.side_effect = _bump_generation

    await rt._stop_locked()
    assert rt._client is client
    assert rt._uba_id == 1381


@pytest.mark.asyncio
async def test_stop_clears_same_generation() -> None:
    from stock_platform.realtime.kiwoom_market_realtime_runtime import (
        KiwoomMarketRealtimeRuntime,
    )

    rt = KiwoomMarketRealtimeRuntime()
    rt._generation = 1
    client = MagicMock()
    client.shutdown = AsyncMock()
    client.note_exit_reason = MagicMock()
    rt._client = client
    rt._task = asyncio.create_task(asyncio.sleep(60))
    rt._uba_id = 1381
    rt._started_at = datetime.now(timezone.utc)

    out = await rt._stop_locked()
    assert out["stopped"] is True
    assert rt._client is None
    assert rt._uba_id is None


def test_client_lifecycle_fields_in_status() -> None:
    from stock_platform.broker.kiwoom.market_realtime_client import (
        KiwoomMarketRealtimeClient,
    )
    from stock_platform.broker.kiwoom.token_cache import KiwoomTokenCache
    from stock_platform.broker.kiwoom.ws_config import KiwoomMarketWebSocketConfig

    cfg = KiwoomMarketWebSocketConfig.for_real_host()
    cache = MagicMock(spec=KiwoomTokenCache)
    client = KiwoomMarketRealtimeClient(
        config=cfg,
        token_cache=cache,
        generation_id=7,
    )
    st = client.status()
    assert st["generation_id"] == 7
    assert st["lifecycle"]["generation_id"] == 7
    assert st["lifecycle"]["tick_count"] == 0
