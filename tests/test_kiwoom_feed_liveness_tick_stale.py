"""KIWOOM feed liveness vs TICK_STALE false-positive regression tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.trading.autotrading_data_trust import (
    QUALITY_VALID,
    evaluate_data_trust_from_health,
)
from stock_platform.trading.autotrading_health_slo import AutotradingHealthSlo
from stock_platform.trading.kiwoom_feed_liveness import (
    evaluate_kiwoom_feed_liveness,
    kiwoom_feed_connection_failure,
    kiwoom_feed_is_real_idle,
)
from stock_platform.trading.kiwoom_feed_recovery import (
    ensure_kiwoom_feed_fresh,
    kiwoom_feed_needs_l1_recovery,
    kiwoom_runtime_feed_is_stale,
)


def _slo() -> AutotradingHealthSlo:
    return AutotradingHealthSlo(feed_max_age_seconds=30.0)


def _runtime_idle_liveness() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "running": True,
        "connected": True,
        "generation_id": 3,
        "feed_age_seconds": 45.0,
        "started_at": (now - timedelta(minutes=5)).isoformat(),
        "client": {
            "reg_ack": True,
            "event_count": 100,
            "frame_count": 500,
            "last_event_at": (now - timedelta(seconds=45)).isoformat(),
            "last_frame_at": (now - timedelta(seconds=5)).isoformat(),
            "last_ping_at": (now - timedelta(seconds=5)).isoformat(),
        },
    }


def test_real_idle_when_frame_recent_tick_stale() -> None:
    st = _runtime_idle_liveness()
    assert kiwoom_feed_is_real_idle(st, slo=_slo()) is True
    lv = evaluate_kiwoom_feed_liveness(st, slo=_slo())
    assert lv["connection_liveness_ok"] is True
    assert lv["market_tick_stale"] is True


def test_connection_failure_when_no_frame_liveness() -> None:
    now = datetime.now(timezone.utc)
    st = {
        "running": True,
        "connected": True,
        "feed_age_seconds": 45.0,
        "client": {
            "reg_ack": True,
            "event_count": 10,
            "last_event_at": (now - timedelta(seconds=45)).isoformat(),
            "last_frame_at": (now - timedelta(seconds=60)).isoformat(),
        },
    }
    assert kiwoom_feed_connection_failure(st, slo=_slo()) is True
    assert kiwoom_feed_is_real_idle(st, slo=_slo()) is False


def test_runtime_not_stale_on_real_idle() -> None:
    assert (
        kiwoom_runtime_feed_is_stale(_runtime_idle_liveness(), slo=_slo()) is False
    )


def test_l1_not_needed_for_real_idle_health() -> None:
    health = {
        "components": {"feed": "REAL_IDLE"},
        "feed_detail": {"ok": True, "reason": "NO_TRADE_TICK_IDLE"},
    }
    with patch(
        "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime"
    ) as kmr:
        kmr.status.return_value = _runtime_idle_liveness()
        assert not kiwoom_feed_needs_l1_recovery(health, slo=_slo())


def test_data_trust_valid_on_real_idle() -> None:
    ev = evaluate_data_trust_from_health(
        {
            "components": {
                "runtime": "RUNNING",
                "runner": "RUNNING",
                "worker": "RUNNING",
                "exit_monitor": "RUNNING",
                "feed": "REAL_IDLE",
                "scanner": "RUNNING",
            },
            "watchdog": {"running": True},
            "invariants": {},
            "open_count": 0,
            "no_trade_classification": "NORMAL_NO_SIGNAL",
        }
    )
    assert ev["quality_status"] == QUALITY_VALID


@pytest.mark.asyncio
async def test_ensure_skips_hard_reconnect_on_real_idle() -> None:
    session = MagicMock()
    runtime = MagicMock()
    runtime.status.return_value = _runtime_idle_liveness()
    runtime.start = AsyncMock(return_value={"started": True, "connected": True})
    runtime.stop = AsyncMock()

    health = {
        "components": {"feed": "STALE"},
        "feed_detail": {"reason": "TICK_STALE", "age_seconds": 45.0},
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
    assert out.get("liveness_ok") is True


def test_health_builds_real_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.trading.autotrading_health_service import (
        build_trading_health_snapshot,
    )

    session = MagicMock()
    uba = MagicMock()
    uba.broker_code = "KIWOOM"
    uba.live_order_enabled = True
    uba.live_armed = True
    uba.arm_expires_at = None
    session.get.return_value = uba

    st = _runtime_idle_liveness()

    with (
        patch(
            "stock_platform.trading.autotrading_health_service.combined_control_status",
            return_value={},
        ),
        patch(
            "stock_platform.trading.autotrading_health_service._resolve_stack_components",
            return_value={
                "runtime": "RUNNING",
                "worker": "RUNNING",
                "exit_monitor": "RUNNING",
                "runner": "RUNNING",
                "runner_detail": {},
                "ops24": None,
            },
        ),
        patch(
            "stock_platform.trading.autotrading_health_service.LiveTradingTransitionService"
        ) as lts_cls,
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime"
        ) as kmr,
        patch(
            "stock_platform.trading.autotrading_health_service._collect_heartbeats",
            return_value={},
        ),
        patch(
            "stock_platform.trading.autotrading_health_service._invariants",
            return_value={},
        ),
        patch(
            "stock_platform.trading.autotrading_health_service._kiwoom_session_allows_stack_slo",
            return_value=True,
        ),
        patch(
            "stock_platform.trading.execution_stack_reconciliation.detect_runtime_control_mismatch",
            return_value={"mismatch_kind": None},
        ),
        patch(
            "stock_platform.trading.kiwoom_funnel_observability.build_kiwoom_funnel_snapshot",
            return_value={},
        ),
    ):
        lts_cls.return_value.peek_active.return_value = object()
        kmr.status.return_value = st
        snap = build_trading_health_snapshot(session, user_broker_account_id=1381)

    assert snap["components"]["feed"] == "REAL_IDLE"
    assert snap["feed_detail"]["reason"] == "NO_TRADE_TICK_IDLE"
    assert snap["feed_detail"]["ok"] is True


@pytest.mark.asyncio
async def test_startup_grace_blocks_l1_on_connecting() -> None:
    health = {
        "components": {"feed": "CONNECTING"},
        "feed_detail": {"reason": "NO_REAL_TICK_YET", "ok": False},
    }
    with (
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime"
        ) as kmr,
        patch(
            "stock_platform.trading.kiwoom_feed_recovery._process_in_startup_grace",
            return_value=True,
        ),
    ):
        kmr.status.return_value = {
            "running": True,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "client": {"event_count": 0, "reg_ack": True},
            "connected": True,
        }
        assert not kiwoom_feed_needs_l1_recovery(health, slo=_slo())
