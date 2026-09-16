"""AutotradingOrchestrator unit tests — REAL broker mutation 없음."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.trading.autotrading_orchestrator import (
    STATUS_ALREADY_RUNNING,
    STATUS_BLOCKED,
    STATUS_READY,
    STATUS_STOPPED,
    AutotradingOrchestrator,
    STOP_ENTRY_ONLY,
)


@pytest.mark.asyncio
async def test_start_uba_not_found():
    session = MagicMock()
    session.get.return_value = None
    out = await AutotradingOrchestrator(session).start(999999, actor="t")
    assert out["status"] == STATUS_BLOCKED
    assert out["reason_code"] == "UBA_NOT_FOUND"


@pytest.mark.asyncio
async def test_start_upbit_already_running():
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        live_order_enabled=True,
        live_armed=True,
    )
    session = MagicMock()
    session.get.return_value = uba

    with (
        patch(
            "stock_platform.trading.autotrading_orchestrator.LiveUnattendedAuthorizationService"
        ) as Unatt,
        patch(
            "stock_platform.trading.autotrading_orchestrator.evaluate_uba_autotrading_ready"
        ) as ready,
    ):
        Unatt.return_value.status_dict.return_value = {
            "needs_reauthorize": False,
            "status_code": "ACTIVE",
        }
        ready.return_value = {
            "status": "READY_FOR_AUTO_TRADING",
            "blockers": [],
        }
        out = await AutotradingOrchestrator(session).start(1380, actor="t")
    assert out["status"] == STATUS_ALREADY_RUNNING
    assert out["message_code"] == "ORCH_ALREADY_RUNNING"


@pytest.mark.asyncio
async def test_start_blocked_without_reauthorize_when_needed():
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        live_order_enabled=False,
        live_armed=False,
    )
    session = MagicMock()
    session.get.return_value = uba

    with (
        patch(
            "stock_platform.trading.autotrading_orchestrator.LiveUnattendedAuthorizationService"
        ) as Unatt,
        patch(
            "stock_platform.trading.autotrading_orchestrator.evaluate_uba_autotrading_ready"
        ) as ready,
    ):
        Unatt.return_value.status_dict.return_value = {
            "needs_reauthorize": True,
            "status_code": "PROTECTIVE_EXIT_ONLY",
        }
        ready.return_value = {"status": "BLOCKED", "blockers": ["ARM_OFF"]}
        out = await AutotradingOrchestrator(session).start(
            1380, actor="t", reauthorize_unattended=False
        )
    assert out["status"] == STATUS_BLOCKED
    assert out["reason_code"] == "UNATTENDED_NEEDS_REAUTHORIZE"
    assert out["failed_step"] == "unattended_reauthorize"


@pytest.mark.asyncio
async def test_start_upbit_stack_restore_ready():
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        live_order_enabled=True,
        live_armed=True,
    )
    session = MagicMock()
    session.get.return_value = uba
    session.refresh = MagicMock()

    with (
        patch(
            "stock_platform.trading.autotrading_orchestrator.LiveUnattendedAuthorizationService"
        ) as Unatt,
        patch(
            "stock_platform.trading.autotrading_orchestrator.evaluate_uba_autotrading_ready"
        ) as ready,
        patch(
            "stock_platform.trading.autotrading_orchestrator.evaluate_stack_restore_gates"
        ) as gates,
        patch(
            "stock_platform.trading.autotrading_orchestrator.restore_upbit_trading_stack",
            new_callable=AsyncMock,
        ) as restore,
        patch(
            "stock_platform.operation.upbit_full_market.service.UpbitFullMarketAssignmentService"
        ) as Fm,
    ):
        Unatt.return_value.status_dict.return_value = {
            "needs_reauthorize": False,
            "status_code": "ACTIVE",
        }
        Unatt.return_value.evaluate_enable_gates.return_value = {
            "ok": True,
            "blockers": [],
            "checks": {},
        }
        ready.side_effect = [
            {"status": "DEGRADED", "blockers": ["RUNTIME_NOT_RUNNING"]},
            {"status": "READY_FOR_AUTO_TRADING", "blockers": []},
        ]
        gates.return_value = {"ok": True, "blockers": []}
        restore.return_value = {
            "restored": True,
            "detail": {
                "worker": {"started": True, "reason": "ALREADY_RUNNING"},
                "runtime": {"resumed": True, "reason": "ALREADY_RUNNING"},
                "exit": {"started": False, "reason": "ALREADY"},
                "execution_runner": {"started": True, "reason": "ALREADY_RUNNING"},
                "portfolio_entry_context": {"ok": True},
            },
        }
        Fm.return_value.status_dict.return_value = {"strategy_id": 17483}
        out = await AutotradingOrchestrator(session).start(1380, actor="t")
    assert out["status"] == STATUS_READY
    assert out["readiness"] == "READY_FOR_AUTO_TRADING"
    restore.assert_awaited()


@pytest.mark.asyncio
async def test_stop_entry_only_keeps_protective():
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
    )
    session = MagicMock()
    session.get.return_value = uba

    with (
        patch(
            "stock_platform.operation.upbit_full_market.service.UpbitFullMarketAssignmentService"
        ) as Fm,
        patch(
            "stock_platform.trading.autotrading_orchestrator.stop_upbit_strategy_runtime",
            new_callable=AsyncMock,
        ) as stop_rt,
        patch(
            "stock_platform.realtime.runtime.realtime_execution_runner_manager"
        ) as runner,
    ):
        Fm.return_value.status_dict.return_value = {"strategy_id": 17483}
        stop_rt.return_value = {"stopped": True}
        runner.get.return_value = None
        out = await AutotradingOrchestrator(session).stop(
            1380, actor="t", mode=STOP_ENTRY_ONLY
        )
    assert out["status"] == STATUS_STOPPED
    assert out["message_code"] == "ORCH_STOP_ENTRY_ONLY"
    names = [s["name"] for s in out["steps"]]
    assert "protective_keep" in names
    stop_rt.assert_awaited()


@pytest.mark.asyncio
async def test_full_stop_blocked_when_open_positions():
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
    )
    session = MagicMock()
    session.get.return_value = uba

    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_service.UpbitPortfolioService"
    ) as Pf:
        Pf.return_value.list_slots.return_value = [
            {"status": "OPEN", "symbol": "KRW-BTC"}
        ]
        out = await AutotradingOrchestrator(session).stop(
            1380, actor="t", mode="FULL"
        )
    assert out["status"] == STATUS_BLOCKED
    assert out["reason_code"] == "OPEN_AUTO_POSITIONS_PRESENT"


@pytest.mark.asyncio
async def test_kiwoom_status_skips_upbit_master_gate():
    """KIWOOM /status readiness는 ops SoT — UPBIT gate 오탐 금지."""
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
    )
    session = MagicMock()
    session.get.return_value = uba
    ops = {
        "user_broker_account_id": 1381,
        "auto_trading_ready": True,
        "blockers": [],
        "warnings": ["ACTIVATION_HORIZON_MISMATCH"],
        "live": "ON",
        "arm": "ON",
        "activation": "ACTIVE",
        "runtime_stack": {"label": "4/4 RUNNING"},
        "market_feed": {"status": "REAL_FRESH"},
        "reliability": {"health_state": "HEALTHY", "health_reasons": []},
    }

    with (
        patch(
            "stock_platform.trading.autotrading_orchestrator.evaluate_uba_autotrading_ready"
        ) as ready,
        patch(
            "stock_platform.trading.uba_operational_summary.build_uba_operational_summary",
            return_value=ops,
        ),
    ):
        out = await AutotradingOrchestrator(session).status(1381)

    ready.assert_not_called()
    assert out["broker"] == "KIWOOM"
    assert out["readiness"]["checks"]["upbit_master_gate_skipped"] is True
    assert out["readiness"]["checks"]["source"] == "KIWOOM_OPS_SUMMARY"
    assert "UBA_BROKER_MISMATCH" not in (out["readiness"].get("blockers") or [])
    assert "UPBIT_CREDENTIAL_UNRESOLVED" not in (
        out["readiness"].get("blockers") or []
    )


def test_kiwoom_status_readiness_filters_upbit_noise():
    from stock_platform.trading.autotrading_orchestrator import (
        _kiwoom_status_readiness_from_ops,
    )

    out = _kiwoom_status_readiness_from_ops(
        {
            "user_broker_account_id": 1381,
            "auto_trading_ready": False,
            "blockers": [],
            "warnings": ["UPBIT_LIVE_ORDER_FLAG_ON", "ACTIVATION_HORIZON_MISMATCH"],
            "reliability": {
                "health_state": "BROKEN",
                "health_reasons": ["FEED_UNHEALTHY"],
            },
        }
    )
    assert "UPBIT_LIVE_ORDER_FLAG_ON" not in out["warnings"]
    assert "FEED_UNHEALTHY" in out["blockers"]
    assert out["auto_trading_ready"] is False
    assert out["status"] == "BLOCKED"
