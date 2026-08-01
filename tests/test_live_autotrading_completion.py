"""LIVE autotrading wiring — Fail Closed unit tests (실주문 HTTP 0)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.realtime.execution_models import RealtimeExecutionMode
from stock_platform.realtime.live_runtime_control import (
    apply_realtime_live_execution_config,
    live_auto_start_allowed,
    live_order_flags_ready,
    revert_realtime_execution_to_paper,
)
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_safety_guard,
)


def test_live_auto_start_fail_closed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REALTIME_EXECUTION_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("REALTIME_LIVE_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache, get_settings

    clear_settings_cache()
    settings = get_settings()
    assert live_order_flags_ready(settings) is False
    gate = live_auto_start_allowed(allow_live=True)
    assert gate["allowed"] is False


def test_live_config_requires_unlock_and_uba(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "false")
    monkeypatch.setenv("REALTIME_LIVE_UNLOCK_TOKEN", "")
    monkeypatch.setenv("REALTIME_LIVE_USER_BROKER_ACCOUNT_ID", "0")
    monkeypatch.setenv("REALTIME_PAPER_ACCOUNT_ID", "1")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    # 기존 mode 보존 후 복구
    prev = realtime_execution_runner._config
    try:
        result = apply_realtime_live_execution_config(user_broker_account_id=0)
        assert result["applied"] is False
        assert result["reason"] in {
            "LIVE_UNLOCK_TOKEN_MISSING",
            "LIVE_UBA_MISSING",
        }
    finally:
        realtime_execution_runner._config = prev


def test_live_config_apply_and_revert(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "false")
    monkeypatch.setenv("REALTIME_LIVE_UNLOCK_TOKEN", "TEST-UNLOCK")
    monkeypatch.setenv("REALTIME_LIVE_USER_BROKER_ACCOUNT_ID", "42")
    monkeypatch.setenv("REALTIME_PAPER_ACCOUNT_ID", "1")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    prev_cfg = realtime_execution_runner._config
    prev_safe = realtime_safety_guard._config
    try:
        applied = apply_realtime_live_execution_config()
        assert applied["applied"] is True
        assert realtime_execution_runner._config.mode == RealtimeExecutionMode.LIVE
        assert realtime_execution_runner._config.user_broker_account_id == 42
        assert realtime_safety_guard._config.live_trading_enabled is True
        assert realtime_safety_guard._config.live_unlock_token == "TEST-UNLOCK"

        reverted = revert_realtime_execution_to_paper()
        assert reverted["mode"] == "PAPER"
        assert realtime_execution_runner._config.mode == RealtimeExecutionMode.PAPER
        assert realtime_safety_guard._config.live_trading_enabled is False
    finally:
        realtime_execution_runner._config = prev_cfg
        realtime_safety_guard._config = prev_safe
        clear_settings_cache()


def test_upbit_fill_ledger_hook_invoked() -> None:
    from stock_platform.broker.upbit.fill_sync_service import UpbitFillSyncService

    session = MagicMock()
    svc = UpbitFillSyncService.__new__(UpbitFillSyncService)
    svc._session = session
    order = SimpleNamespace(
        order_id=1,
        broker_order_id="u1",
        symbol="KRW-BTC",
        side_code="BUY",
        remaining_quantity=Decimal("0"),
        user_broker_account_id=9,
    )
    # 메서드 존재·예외 흡수 확인
    svc._apply_live_fill_ledger(
        order=order,
        remote={"uuid": "u1", "executed_volume": "0.01"},
        new_execution_ids=[],
        actor="TEST",
    )


@pytest.mark.asyncio
async def test_market_open_live_gate_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REALTIME_EXECUTION_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("REALTIME_LIVE_AUTO_START_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache
    from stock_platform.realtime.live_runtime_control import (
        live_auto_start_allowed,
    )

    clear_settings_cache()
    gate = live_auto_start_allowed(allow_live=True)
    assert gate["allowed"] is False
