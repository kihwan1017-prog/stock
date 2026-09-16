"""Integrated Runtime/Scheduler PostgreSQL E2E.

Paper / MOCK / Upbit Shadow lifecycle — LIVE submit 0.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.realtime.execution_models import RealtimeExecutionMode
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_strategy_runner,
)
from stock_platform.realtime.session_models import TradingSessionPhase


@pytest.fixture
def _flags_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REALTIME_EXECUTION_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("REALTIME_PAPER_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("REALTIME_KIWOOM_MOCK_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("REALTIME_LIVE_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("REALTIME_UPBIT_SHADOW_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("LIVE_SHADOW_MODE_ENABLED", "false")
    monkeypatch.setenv("LIVE_ORDER_DRY_RUN_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.mark.asyncio
async def test_all_auto_flags_off_no_auto_start(_flags_off) -> None:
    from stock_platform.realtime.execution_auto_start import (
        maybe_auto_start_runners,
    )

    result = await maybe_auto_start_runners(source="TEST", allow_live=False)
    assert result["skipped_reason"] == "MASTER_FLAG_OFF"
    assert result["started_execution"] is False


@pytest.mark.asyncio
async def test_market_open_close_paper_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REALTIME_EXECUTION_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("REALTIME_PAPER_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("REALTIME_KIWOOM_MOCK_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("REALTIME_UPBIT_SHADOW_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("REALTIME_PAPER_ACCOUNT_ID", "1")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()

    from stock_platform.database.session import get_session_factory
    from stock_platform.realtime.session_service import (
        RealtimeTradingSessionService,
    )

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        svc = RealtimeTradingSessionService(session)
        # Calendar 우회 — trading day로 강제
        with patch.object(
            svc._calendar,
            "evaluate",
            return_value=MagicMock(
                is_trading_day=True,
                live_allowed=True,
                reason_code="CALENDAR_OPEN",
            ),
        ):
            open1 = await svc.execute(phase=TradingSessionPhase.MARKET_OPEN)
            open2 = await svc.execute(phase=TradingSessionPhase.MARKET_OPEN)
            assert open1.executed is True
            assert open2.executed is True
            assert realtime_execution_runner.status()["running"] is True

            close1 = await svc.execute(phase=TradingSessionPhase.MARKET_CLOSE)
            close2 = await svc.execute(phase=TradingSessionPhase.MARKET_CLOSE)
            assert close1.executed is True
            assert close2.executed is True
            assert realtime_execution_runner.status()["running"] is False

    await realtime_strategy_runner.stop()
    clear_settings_cache()


@pytest.mark.asyncio
async def test_market_close_keeps_upbit_when_shadow_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REALTIME_EXECUTION_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("REALTIME_PAPER_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("REALTIME_UPBIT_SHADOW_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("LIVE_SHADOW_MODE_ENABLED", "true")
    monkeypatch.setenv("LIVE_ORDER_DRY_RUN_ENABLED", "false")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("REALTIME_PAPER_ACCOUNT_ID", "1")
    monkeypatch.setenv("REALTIME_LIVE_USER_BROKER_ACCOUNT_ID", "58")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()

    from stock_platform.realtime.integrated_runtime_lifecycle import (
        on_market_close,
        on_market_open,
    )
    from stock_platform.realtime.manager import realtime_manager

    # fake upbit client already running
    fake = MagicMock()
    fake.status.return_value = {
        "connected": True,
        "reconnect_count": 0,
        "received_count": 1,
    }
    realtime_manager._clients["UPBIT"] = fake
    realtime_manager._tasks["UPBIT"] = MagicMock()

    with patch(
        "stock_platform.realtime.integrated_runtime_lifecycle._kill_switch_blocks",
        return_value=(False, None),
    ):
        opened = await on_market_open()
        assert opened.get("started") is True
        closed = await on_market_close()

    assert closed.get("keep_upbit") is True
    assert "UPBIT" in (realtime_manager._tasks or {})
    # cleanup
    realtime_manager._clients.pop("UPBIT", None)
    realtime_manager._tasks.pop("UPBIT", None)
    await realtime_execution_runner.stop()
    await realtime_strategy_runner.stop()
    clear_settings_cache()


@pytest.mark.asyncio
async def test_kill_switch_blocks_market_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REALTIME_EXECUTION_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("REALTIME_PAPER_AUTO_START_ENABLED", "true")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()

    from stock_platform.realtime.integrated_runtime_lifecycle import (
        on_market_open,
    )

    with patch(
        "stock_platform.realtime.integrated_runtime_lifecycle._kill_switch_blocks",
        return_value=(True, "KILL_SWITCH_ACTIVE"),
    ):
        result = await on_market_open()
    assert result.get("started") is False
    assert result.get("skipped_reason") == "KILL_SWITCH_ACTIVE"
    clear_settings_cache()


@pytest.mark.asyncio
async def test_stop_feeds_keep_upbit() -> None:
    from stock_platform.realtime.live_runtime_control import (
        stop_live_market_feeds,
    )
    from stock_platform.realtime.manager import realtime_manager

    realtime_manager._clients["UPBIT"] = MagicMock()
    realtime_manager._tasks["UPBIT"] = MagicMock()
    realtime_manager._clients["OTHER"] = MagicMock()
    realtime_manager._tasks["OTHER"] = MagicMock()

    async def _stop(cid: str) -> None:
        realtime_manager._clients.pop(cid, None)
        realtime_manager._tasks.pop(cid, None)

    with patch.object(realtime_manager, "stop", side_effect=_stop):
        result = await stop_live_market_feeds(keep_upbit=True)

    assert result["keep_upbit"] is True
    assert "UPBIT" in realtime_manager._tasks
    assert "OTHER" not in realtime_manager._tasks
    realtime_manager._clients.pop("UPBIT", None)
    realtime_manager._tasks.pop("UPBIT", None)


def test_mock_config_blocked_by_live_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    from stock_platform.realtime.integrated_runtime_lifecycle import (
        apply_realtime_mock_execution_config,
    )

    out = apply_realtime_mock_execution_config(paper_account_id=1)
    assert out["applied"] is False
    assert out["reason"] == "KIWOOM_LIVE_FLAG_ON"
    clear_settings_cache()


def test_lifecycle_monitoring_has_flags(_flags_off) -> None:
    from stock_platform.realtime.integrated_runtime_lifecycle import (
        lifecycle_monitoring_snapshot,
    )

    snap = lifecycle_monitoring_snapshot()
    assert snap["flags"]["master"] is False
    assert snap["flags"]["upbit_live_order"] is False
    assert snap["flags"]["kiwoom_live_order"] is False
    assert "execution" in snap
    assert "session_scheduler" in snap


@pytest.mark.asyncio
async def test_duplicate_open_does_not_duplicate_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REALTIME_EXECUTION_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("REALTIME_PAPER_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("REALTIME_PAPER_ACCOUNT_ID", "1")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()

    from stock_platform.realtime.integrated_runtime_lifecycle import (
        on_market_open,
    )

    with patch(
        "stock_platform.realtime.integrated_runtime_lifecycle._kill_switch_blocks",
        return_value=(False, None),
    ):
        a = await on_market_open()
        b = await on_market_open()
    assert a.get("started") is True
    assert b.get("started") is True
    # runner start is idempotent (already_running ok)
    assert realtime_execution_runner.status()["running"] is True
    await realtime_execution_runner.stop()
    await realtime_strategy_runner.stop()
    clear_settings_cache()
