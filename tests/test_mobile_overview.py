# -*- coding: utf-8 -*-
"""Mobile overview — read-only unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.api.v1 import mobile as mobile_api
from stock_platform.operation.mobile_overview_service import (
    _broker_card,
    _overall_tone,
    _slim_order,
    _slim_position,
)


@pytest.mark.unit
def test_mobile_router_get_only() -> None:
    flat: set[str] = set()
    for r in mobile_api.router.routes:
        methods = getattr(r, "methods", None) or set()
        flat |= set(methods)
    assert "GET" in flat
    assert not (flat & {"POST", "PUT", "PATCH", "DELETE"})


@pytest.mark.unit
def test_broker_card_null_safe() -> None:
    card = _broker_card({}, side={"auto_buy_count": 0, "auto_sell_count": 0, "fill_count": 0})
    assert card["live"] is False
    assert card["arm"] is False
    assert card["can_auto_trade"] is False
    assert card["runtime"] == "STOPPED"


@pytest.mark.unit
def test_overall_tone_kill_stopped() -> None:
    assert (
        _overall_tone(
            kill_active=True,
            upbit={"auto_trading_state": "RUNNING", "can_auto_trade": True},
            kiwoom={},
        )
        == "STOPPED"
    )


@pytest.mark.unit
def test_overall_tone_healthy() -> None:
    assert (
        _overall_tone(
            kill_active=False,
            upbit={"auto_trading_state": "RUNNING", "can_auto_trade": True},
            kiwoom={"auto_trading_state": "STOPPED"},
        )
        == "HEALTHY"
    )


@pytest.mark.unit
def test_slim_helpers() -> None:
    pos = _slim_position(
        {
            "symbol": "KRW-XRP",
            "broker_code": "UPBIT",
            "quantity": "10",
            "average_price": "100",
            "current_price": "110",
            "unrealized_pnl": "100",
        }
    )
    assert pos["symbol"] == "KRW-XRP"
    assert pos["market"] == "UPBIT"
    order = _slim_order(
        {
            "created_at": "2026-01-01T00:00:00Z",
            "broker_code": "UPBIT",
            "market": "KRW-XRP",
            "side": "BUY",
            "internal_status": "FILLED",
        }
    )
    assert order["symbol"] == "KRW-XRP"
    assert order["status"] == "FILLED"


@pytest.mark.unit
def test_build_mobile_overview_mocked() -> None:
    from stock_platform.operation import mobile_overview_service as mod

    session = MagicMock()
    with (
        patch.object(mod, "measure_db_latency_ms", return_value=("UP", 1.0, None)),
        patch.object(mod, "KillSwitchService") as ks,
        patch.object(
            mod,
            "build_uba_operational_summary",
            side_effect=[
                {
                    "user_broker_account_id": 1380,
                    "broker_code": "UPBIT",
                    "live": "ON",
                    "arm": "ON",
                    "runtime": "RUNNING",
                    "runner": "RUNNING",
                    "outbox_worker": "RUNNING",
                    "exit_monitor": "RUNNING",
                    "auto_trading_state": "RUNNING",
                    "market_feed": {"status": "REAL_FRESH"},
                    "scanner": {"running": True},
                    "blockers": [],
                    "warnings": [],
                },
                {
                    "user_broker_account_id": 1381,
                    "broker_code": "KIWOOM",
                    "live": "OFF",
                    "arm": "OFF",
                    "runtime": "STOPPED",
                    "runner": "STOPPED",
                    "outbox_worker": "RUNNING",
                    "exit_monitor": "RUNNING",
                    "auto_trading_state": "STOPPED",
                    "market_feed": {"status": "REAL_FRESH"},
                    "scanner": {"running": False},
                    "blockers": ["LIVE_OFF"],
                    "warnings": [],
                },
            ],
        ),
        patch.object(
            mod,
            "_side_counts",
            return_value={
                "auto_buy_count": 1,
                "auto_sell_count": 2,
                "fill_count": 2,
            },
        ),
        patch.object(mod, "OpsMonitoringDashboardService") as Ops,
        patch.object(mod, "AutotradingPerformanceService") as Perf,
        patch.object(
            mod, "analysis_config", return_value=SimpleNamespace(model="qwen3:1.7b")
        ),
        patch.object(
            mod, "trading_config", return_value=SimpleNamespace(model="qwen3.5:2b")
        ),
        patch.object(
            mod, "teacher_config", return_value=SimpleNamespace(model="qwen3.5:4b")
        ),
    ):
        ks.return_value.is_active.return_value = False
        ks.return_value.get_state.side_effect = RuntimeError("skip enum")
        ops = Ops.return_value
        ops.overview.return_value = {
            "overall_status": "HEALTHY",
            "scheduler": {"status": "OK"},
            "worker": {"status": "RUNNING"},
        }
        ops.positions.return_value = {"count": 0, "positions": []}
        ops.orders.return_value = {"orders": []}
        ops.alerts.return_value = {"items": []}
        Perf.return_value.build.return_value = {
            "summary": {
                "today_realized_pnl": "1000",
                "current_unrealized_pnl": "-100",
            }
        }
        out = mod.build_mobile_overview(session)

    assert out["schema"] == "mobile_overview_v1"
    assert out["upbit"]["uba_id"] == 1380
    assert out["upbit"]["live"] is True
    assert out["kiwoom"]["live"] is False
    assert out["ai"]["trading_mode"] == "SHADOW"
    assert out["today"]["realized_pnl"] == 1000.0
    assert "api_key" not in str(out).lower()
