"""Kiwoom Process Map overlay — align with funnel/realtime SoT."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.operation.autotrading_process_version.service import (
    _kiwoom_runtime_overlay,
)


def _base_funnel(**overrides):
    base = {
        "ok": True,
        "market_hours": {
            "in_regular_session": True,
            "session_type": "REGULAR",
        },
        "universe": {
            "UNIVERSE_SOURCE": "STRATEGY_FIXED_DEPLOYMENT",
            "UNIVERSE_SYMBOL_COUNT": 1,
            "symbols": ["034310"],
            "034310_ONLY": True,
        },
        "feed": {
            "running": True,
            "connected": True,
            "REAL_TICK_COUNT": 1,
        },
        "funnel": {
            "SCANNED": 1,
            "CANDIDATE": 1,
            "SIGNAL": 0,
        },
        "lifecycle": {"runtime": "RUNNING"},
        "FIRST_ZERO_STAGE": "NO_GOLDEN_CROSS_SIGNAL",
    }
    base.update(overrides)
    return base


def _rt(**overrides):
    base = {
        "user_broker_account_id": 1381,
        "running": True,
        "connected": True,
        "last_tick_at": "2026-08-27T06:30:15+00:00",
        "client": {
            "login_ack": True,
            "reg_ack": True,
            "event_count": 3,
            "symbols": ["034310"],
        },
    }
    base.update(overrides)
    return base


def _fake_kmr_modules(status_return: dict):
    """websockets 없는 환경에서도 lazy-import 가 통과하도록 fake 모듈 주입."""
    realtime_pkg = ModuleType("stock_platform.realtime")
    kmr_mod = ModuleType("stock_platform.realtime.kiwoom_market_realtime_runtime")
    kmr_mod.kiwoom_market_realtime_runtime = SimpleNamespace(
        status=MagicMock(return_value=status_return)
    )
    return {
        "stock_platform.realtime": realtime_pkg,
        "stock_platform.realtime.kiwoom_market_realtime_runtime": kmr_mod,
    }


def test_regular_healthy_feed_node_ok() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.trading.kiwoom_funnel_observability.build_kiwoom_funnel_snapshot",
            return_value=_base_funnel(),
        ),
        patch.dict(sys.modules, _fake_kmr_modules(_rt())),
    ):
        out = _kiwoom_runtime_overlay(session, uba_id=1381)
    assert out["node_status"]["MARKET_DATA"] == "OK"
    assert out["first_zero"] == "NO_GOLDEN_CROSS_SIGNAL"
    assert out["node_status"]["ENTRY_SIGNAL"] == "WAIT"
    assert out["summary"]["pending_issue"] is None
    assert "골든크로스" in out["summary"]["user_friendly_reason"]


def test_regular_feed_down_node_error() -> None:
    session = MagicMock()
    funnel = _base_funnel(
        FIRST_ZERO_STAGE="FEED_DOWN",
        feed={"running": False, "connected": False, "REAL_TICK_COUNT": 0},
    )
    rt = _rt(
        running=False,
        connected=False,
        client={"event_count": 0, "login_ack": False, "reg_ack": False},
    )
    with (
        patch(
            "stock_platform.trading.kiwoom_funnel_observability.build_kiwoom_funnel_snapshot",
            return_value=funnel,
        ),
        patch.dict(sys.modules, _fake_kmr_modules(rt)),
    ):
        out = _kiwoom_runtime_overlay(session, uba_id=1381)
    assert out["node_status"]["MARKET_DATA"] == "ERROR"
    assert out["first_zero"] == "FEED_DOWN"
    assert out["summary"]["pending_issue"] == "KIWOOM_MARKET_DATA_FAILURE"


def test_closed_market_not_feed_down() -> None:
    session = MagicMock()
    funnel = _base_funnel(
        FIRST_ZERO_STAGE="MARKET_CLOSED",
        market_hours={
            "in_regular_session": False,
            "session_type": "REGULAR",
        },
    )
    with (
        patch(
            "stock_platform.trading.kiwoom_funnel_observability.build_kiwoom_funnel_snapshot",
            return_value=funnel,
        ),
        patch.dict(sys.modules, _fake_kmr_modules(_rt())),
    ):
        out = _kiwoom_runtime_overlay(session, uba_id=1381)
    assert out["node_status"]["MARKET_DATA"] == "CLOSED"
    assert out["first_zero"] == "MARKET_CLOSED"
    assert out["first_zero"] != "FEED_DOWN"
    assert out["summary"]["market_status"] == "MARKET_CLOSED"
    assert out["summary"]["pending_issue"] is None
    note = str(out["node_detail"]["MARKET_DATA"].get("note", ""))
    assert out["node_status"]["MARKET_DATA"] != "ERROR"
    assert "시세 장애" not in note or "아님" in note


def test_historical_feed_down_does_not_override_current_healthy() -> None:
    """History/Trace의 FEED_DOWN 은 CURRENT overlay 에 섞이지 않음."""
    session = MagicMock()
    session.scalars.return_value = ["FEED_DOWN_HISTORICAL"]
    with (
        patch(
            "stock_platform.trading.kiwoom_funnel_observability.build_kiwoom_funnel_snapshot",
            return_value=_base_funnel(),
        ),
        patch.dict(sys.modules, _fake_kmr_modules(_rt())),
    ):
        out = _kiwoom_runtime_overlay(session, uba_id=1381)
    assert out["node_status"]["MARKET_DATA"] == "OK"
    assert out["summary"]["historical_feed_down_separated"] is True
    assert out["summary"]["pending_issue"] is None


def test_single_symbol_universe_label() -> None:
    session = MagicMock()
    # DB 조회 실패해도 symbols 폴백으로 단일 종목 표시
    session.scalar.side_effect = RuntimeError("no db in unit test")
    with (
        patch(
            "stock_platform.trading.kiwoom_funnel_observability.build_kiwoom_funnel_snapshot",
            return_value=_base_funnel(
                FIRST_ZERO_STAGE="MARKET_CLOSED",
                market_hours={"in_regular_session": False},
            ),
        ),
        patch.dict(sys.modules, _fake_kmr_modules(_rt())),
    ):
        out = _kiwoom_runtime_overlay(session, uba_id=1381)
    assert out["node_detail"]["UNIVERSE"]["034310_ONLY"] is True
    assert out["node_detail"]["UNIVERSE"]["classification"] == (
        "A_INTENTIONAL_SINGLE_SYMBOL_STRATEGY"
    )
    assert "단일 종목" in out["summary"]["universe_label"]
    assert "034310" in out["summary"]["universe_label"]
    assert out["summary"]["historical_feed_down_separated"] is True
