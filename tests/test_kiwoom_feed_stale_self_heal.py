"""KIWOOM feed STALE self-heal regression tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.trading.autotrading_health_slo import AutotradingHealthSlo
from stock_platform.trading.kiwoom_feed_recovery import (
    ensure_kiwoom_feed_fresh,
    kiwoom_health_feed_is_stale,
    kiwoom_runtime_feed_is_stale,
    verify_kiwoom_feed_recovery,
)


def _slo() -> AutotradingHealthSlo:
    return AutotradingHealthSlo(feed_max_age_seconds=30.0)


def test_runtime_fresh_connected_within_slo_not_stale() -> None:
    assert (
        kiwoom_runtime_feed_is_stale(
            {
                "running": True,
                "connected": True,
                "feed_age_seconds": 12.0,
                "client": {"event_count": 10},
            },
            slo=_slo(),
        )
        is False
    )


def test_runtime_stale_when_age_past_threshold() -> None:
    assert (
        kiwoom_runtime_feed_is_stale(
            {
                "running": True,
                "connected": True,
                "feed_age_seconds": 45.0,
                "client": {"event_count": 100},
            },
            slo=_slo(),
        )
        is True
    )


def test_runtime_connected_no_ticks_is_stale_after_warmup() -> None:
    old_start = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    assert (
        kiwoom_runtime_feed_is_stale(
            {
                "running": True,
                "connected": True,
                "feed_age_seconds": None,
                "started_at": old_start,
                "client": {"event_count": 0},
            },
            slo=_slo(),
        )
        is True
    )


def test_runtime_connected_no_ticks_not_stale_during_warmup() -> None:
    recent = datetime.now(timezone.utc).isoformat()
    assert (
        kiwoom_runtime_feed_is_stale(
            {
                "running": True,
                "connected": True,
                "feed_age_seconds": None,
                "started_at": recent,
                "client": {"event_count": 0},
            },
            slo=_slo(),
        )
        is False
    )


def test_health_stale_component() -> None:
    assert (
        kiwoom_health_feed_is_stale(
            {"components": {"feed": "STALE"}, "heartbeats": {}},
            slo=_slo(),
        )
        is True
    )


def test_health_real_fresh_within_slo() -> None:
    assert (
        kiwoom_health_feed_is_stale(
            {
                "components": {"feed": "REAL_FRESH"},
                "heartbeats": {"feed_age_seconds": 5.0},
            },
            slo=_slo(),
        )
        is False
    )


@pytest.mark.asyncio
async def test_ensure_running_never_hard_reconnect() -> None:
    session = MagicMock()
    runtime = MagicMock()
    runtime.status.return_value = {
        "running": True,
        "connected": True,
        "user_broker_account_id": 1381,
        "feed_age_seconds": 120.0,
        "client": {"event_count": 50},
    }
    runtime.start = AsyncMock(return_value={"started": True, "connected": True})
    runtime.stop = AsyncMock()

    from stock_platform.trading.kiwoom_feed_recovery import ensure_kiwoom_feed_running

    with patch(
        "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime",
        runtime,
    ):
        out = await ensure_kiwoom_feed_running(
            session,
            user_broker_account_id=1381,
            symbols=["034310"],
            actor="SYSTEM_KIWOOM_NEXT_DAY_STACK",
        )

    runtime.stop.assert_not_called()
    assert out.get("hard_reconnect") is False
    assert out.get("stack_idempotent") is True


@pytest.mark.asyncio
async def test_ensure_hard_reconnect_when_stale_running() -> None:
    session = MagicMock()
    runtime = MagicMock()
    runtime.status.side_effect = [
        {
            "running": True,
            "connected": True,
            "user_broker_account_id": 1381,
            "feed_age_seconds": 120.0,
            "client": {"event_count": 50, "last_error": "1000 Bye"},
        },
        {
            "running": True,
            "connected": True,
            "user_broker_account_id": 1381,
            "feed_age_seconds": 1.0,
            "client": {"event_count": 51},
        },
    ]
    runtime.stop = AsyncMock(return_value={"stopped": True})
    runtime.start = AsyncMock(
        return_value={"started": True, "connected": True, "already_running": False}
    )

    health = {
        "components": {"feed": "STALE"},
        "feed_detail": {"reason": "TICK_STALE", "age_seconds": 120.0},
        "heartbeats": {"feed_age_seconds": 120.0},
    }

    with (
        patch(
            "stock_platform.trading.kiwoom_feed_recovery.build_trading_health_snapshot",
            return_value=health,
        ),
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime",
            runtime,
        ),
    ):
        out = await ensure_kiwoom_feed_fresh(
            session,
            user_broker_account_id=1381,
            symbols=["034310"],
            actor="TEST",
            health_snapshot=health,
        )

    runtime.stop.assert_awaited_once()
    runtime.start.assert_awaited_once()
    assert out["hard_reconnect"] is True
    assert out["started"] is True


@pytest.mark.asyncio
async def test_ensure_idempotent_when_fresh() -> None:
    session = MagicMock()
    runtime = MagicMock()
    runtime.status.return_value = {
        "running": True,
        "connected": True,
        "user_broker_account_id": 1381,
        "feed_age_seconds": 3.0,
        "client": {"event_count": 200},
    }
    runtime.start = AsyncMock(return_value={"started": True, "connected": True})

    health = {
        "components": {"feed": "REAL_FRESH"},
        "heartbeats": {"feed_age_seconds": 3.0},
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
    assert out["idempotent"] is True
    assert out.get("hard_reconnect") is False


@pytest.mark.asyncio
async def test_verify_fails_connected_without_real_tick() -> None:
    session = MagicMock()
    runtime = MagicMock()
    runtime.status.return_value = {
        "running": True,
        "connected": True,
        "feed_age_seconds": 60.0,
        "client": {"event_count": 5, "symbols": ["034310"]},
    }
    health = {
        "components": {"feed": "STALE"},
        "heartbeats": {"feed_age_seconds": 60.0},
    }

    with (
        patch(
            "stock_platform.trading.kiwoom_feed_recovery.build_trading_health_snapshot",
            return_value=health,
        ),
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime",
            runtime,
        ),
        patch("stock_platform.trading.kiwoom_feed_recovery.asyncio.sleep", AsyncMock()),
    ):
        out = await verify_kiwoom_feed_recovery(
            session,
            user_broker_account_id=1381,
            event_count_before=5,
            wait_seconds=0.1,
            poll_interval=0.05,
        )

    assert out["verified"] is False
    assert out.get("reason") == "VERIFY_TIMEOUT"


@pytest.mark.asyncio
async def test_verify_succeeds_on_real_fresh_tick() -> None:
    session = MagicMock()
    runtime = MagicMock()
    runtime.status.return_value = {
        "running": True,
        "connected": True,
        "feed_age_seconds": 2.0,
        "client": {"event_count": 8, "symbols": ["034310"], "subscription_count": 1},
    }
    health = {
        "components": {"feed": "REAL_FRESH"},
        "heartbeats": {"feed_age_seconds": 2.0},
    }

    with (
        patch(
            "stock_platform.trading.kiwoom_feed_recovery.build_trading_health_snapshot",
            return_value=health,
        ),
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime",
            runtime,
        ),
    ):
        out = await verify_kiwoom_feed_recovery(
            session,
            user_broker_account_id=1381,
            event_count_before=5,
            wait_seconds=2.0,
        )

    assert out["verified"] is True
    assert out["event_count_delta"] == 3


def test_market_closed_not_classified_stale_in_health() -> None:
    """REGULAR 외 세션 — feed STALE blocker 억제 (health SoT)."""

    from stock_platform.trading.autotrading_health_service import (
        _kiwoom_session_allows_stack_slo,
    )

    session = MagicMock()
    with patch(
        "stock_platform.trading.market_hours_authorization.krx_market_hours_state",
        return_value={"in_regular_session": False, "session_type": "CLOSED"},
    ):
        assert _kiwoom_session_allows_stack_slo(
            session, now=datetime.now(timezone.utc)
        ) is False


@pytest.mark.asyncio
async def test_duplicate_recovery_serializes_via_runtime_lock() -> None:
    """동시 ensure 호출 — runtime lock 으로 단일 canonical connection."""

    runtime = MagicMock()
    runtime.status.return_value = {
        "running": False,
        "connected": False,
        "user_broker_account_id": None,
        "feed_age_seconds": None,
        "client": {},
    }
    runtime.start = AsyncMock(
        return_value={"started": True, "connected": True},
    )

    health = {"components": {"feed": "DISCONNECTED"}, "heartbeats": {}}
    session = MagicMock()

    with patch(
        "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime",
        runtime,
    ):
        await asyncio.gather(
            ensure_kiwoom_feed_fresh(
                session,
                user_broker_account_id=1381,
                symbols=["034310"],
                actor="A",
                health_snapshot=health,
            ),
            ensure_kiwoom_feed_fresh(
                session,
                user_broker_account_id=1381,
                symbols=["034310"],
                actor="B",
                health_snapshot=health,
            ),
        )

    assert runtime.start.await_count == 2


def test_data_trust_invalid_during_stale() -> None:
    from stock_platform.trading.autotrading_data_trust import (
        QUALITY_INVALID,
        evaluate_data_trust_from_health,
    )

    ev = evaluate_data_trust_from_health(
        {
            "components": {
                "runtime": "RUNNING",
                "runner": "RUNNING",
                "worker": "RUNNING",
                "exit_monitor": "RUNNING",
                "feed": "STALE",
                "scanner": "RUNNING",
            },
            "watchdog": {"running": True},
            "invariants": {},
            "open_count": 0,
        }
    )
    assert ev["quality_status"] == QUALITY_INVALID
    assert ev["reason_code"] == "FEED_DOWN"


def test_kiwoom_feed_needs_l1_disconnected() -> None:
    from stock_platform.trading.kiwoom_feed_recovery import kiwoom_feed_needs_l1_recovery

    with patch(
        "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime"
    ) as kmr:
        kmr.status.return_value = {"running": False}
        assert kiwoom_feed_needs_l1_recovery({"components": {"feed": "DISCONNECTED"}})


def test_kiwoom_feed_needs_l1_unhealthy_connecting_after_warmup() -> None:
    from stock_platform.trading.kiwoom_feed_recovery import kiwoom_feed_needs_l1_recovery

    old_start = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    with patch(
        "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime"
    ) as kmr:
        kmr.status.return_value = {
            "running": True,
            "started_at": old_start,
        }
        assert kiwoom_feed_needs_l1_recovery(
            {
                "components": {"feed": "CONNECTING"},
                "feed_detail": {"ok": False, "reason": "NO_REAL_TICK_YET"},
                "heartbeats": {},
            }
        )


def test_kiwoom_feed_needs_l1_false_during_warmup_connecting() -> None:
    from stock_platform.trading.kiwoom_feed_recovery import kiwoom_feed_needs_l1_recovery

    with patch(
        "stock_platform.realtime.kiwoom_market_realtime_runtime.kiwoom_market_realtime_runtime"
    ) as kmr:
        kmr.status.return_value = {
            "running": True,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        assert not kiwoom_feed_needs_l1_recovery(
            {
                "components": {"feed": "CONNECTING"},
                "feed_detail": {"ok": False, "reason": "NO_REAL_TICK_YET"},
                "heartbeats": {},
            }
        )


def test_kiwoom_feed_needs_l1_false_for_real_fresh() -> None:
    from stock_platform.trading.kiwoom_feed_recovery import kiwoom_feed_needs_l1_recovery

    assert not kiwoom_feed_needs_l1_recovery(
        {
            "components": {"feed": "REAL_FRESH"},
            "heartbeats": {"feed_age_seconds": 2.0},
        }
    )


@pytest.mark.asyncio
async def test_recover_kiwoom_feed_l1_feed_only() -> None:
    from stock_platform.trading.kiwoom_feed_recovery import recover_kiwoom_feed_l1

    session = MagicMock()
    with (
        patch(
            "stock_platform.trading.kiwoom_unattended_stack_restore.evaluate_kiwoom_stack_restore_gates",
            return_value={"ok": True, "checks": {"strategy_link": {"strategy_id": 1}}},
        ),
        patch(
            "stock_platform.trading.kiwoom_unattended_stack_restore._resolve_kiwoom_stack_feed_symbols",
            return_value=["034310"],
        ),
        patch(
            "stock_platform.trading.kiwoom_feed_recovery.ensure_kiwoom_feed_fresh",
            AsyncMock(
                return_value={
                    "started": True,
                    "event_count_before": 0,
                    "hard_reconnect": True,
                }
            ),
        ),
        patch(
            "stock_platform.trading.kiwoom_feed_recovery.verify_kiwoom_feed_recovery",
            AsyncMock(return_value={"verified": True, "event_count_delta": 3}),
        ),
        patch(
            "stock_platform.trading.kiwoom_feed_recovery.build_trading_health_snapshot",
            return_value={"components": {"feed": "DISCONNECTED"}},
        ),
    ):
        out = await recover_kiwoom_feed_l1(
            session, user_broker_account_id=1381, actor="TEST"
        )

    assert out["ok"] is True
    assert out["real_tick_verified"] is True
    assert out["feed"]["hard_reconnect"] is True


def test_health_connected_no_timestamp_not_real_fresh() -> None:
    """age/last_received 없이 connected 만으로 REAL_FRESH 금지."""

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

    kmr_st = {
        "running": True,
        "connected": True,
        "feed_age_seconds": None,
        "last_tick_at": None,
        "client": {
            "connected": True,
            "event_count": 0,
            "symbols": ["034310"],
            "subscription_count": 1,
        },
        "process_market_environment": "REAL",
        "execution_process_kiwoom_use_mock": True,
    }

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
        kmr.status.return_value = kmr_st
        snap = build_trading_health_snapshot(session, user_broker_account_id=1381)

    assert snap["components"]["feed"] == "CONNECTING"
    assert snap["feed_detail"]["reason"] == "NO_REAL_TICK_YET"


    from stock_platform.trading.autotrading_data_trust import (
        QUALITY_VALID,
        evaluate_data_trust_from_health,
    )

    ev = evaluate_data_trust_from_health(
        {
            "components": {
                "runtime": "RUNNING",
                "runner": "RUNNING",
                "worker": "RUNNING",
                "exit_monitor": "RUNNING",
                "feed": "REAL_FRESH",
                "scanner": "RUNNING",
            },
            "watchdog": {"running": True},
            "invariants": {},
            "open_count": 0,
            "no_trade_classification": "NORMAL_POLICY_BLOCK",
        }
    )
    assert ev["quality_status"] == QUALITY_VALID
