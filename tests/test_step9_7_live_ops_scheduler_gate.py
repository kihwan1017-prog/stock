"""Live-ops readiness — Trading Scheduler RUN 은 BLOCKED 가 아님."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.api.v1.admin_live_ops_readiness import (
    admin_live_ops_readiness,
)
from stock_platform.risk_engine.kill_switch_models import KillSwitchStatus


class _Snap:
    def __init__(self, *, trading_running: bool | None, actual: str, source: str):
        self.trading_running = trading_running
        self._actual = actual
        self._source = source

    def to_dict(self) -> dict:
        return {
            "trading_scheduler_actual_state": self._actual,
            "trading_scheduler_desired_state": "RUN"
            if self._actual == "RUNNING"
            else "PAUSE",
            "trading_scheduler_paused": self._actual == "PAUSED",
            "tracking_scheduler_running": True,
            "post_fill_scheduler_running": True,
            "source": self._source,
        }


def _call(session: MagicMock, snap: _Snap) -> dict:
    settings = SimpleNamespace(
        upbit_use_mock=False,
        upbit_live_track_enabled=True,
        post_fill_verify_enabled=True,
        upbit_live_order_enabled=False,
        global_live_order_enabled=False,
    )
    kill = SimpleNamespace(status=KillSwitchStatus.INACTIVE)

    def scalar(stmt):  # noqa: ANN001
        # count queries — return 1 for upbit presence
        return 1

    session.scalar.side_effect = scalar

    with (
        patch(
            "stock_platform.api.v1.admin_live_ops_readiness.get_settings",
            return_value=settings,
        ),
        patch(
            "stock_platform.api.v1.admin_live_ops_readiness.KillSwitchService",
            return_value=SimpleNamespace(get_state=lambda: kill),
        ),
        patch(
            "stock_platform.trading.upbit_scheduler_readiness.collect_scheduler_readiness",
            return_value=snap,
        ),
        patch(
            "stock_platform.trading.upbit_live_pipeline_readiness.UpbitLivePipelineReadinessService",
            return_value=SimpleNamespace(evaluate=lambda: {"ok": True}),
        ),
    ):
        return admin_live_ops_readiness(session=session, _=MagicMock())


def test_scheduler_running_is_ready_not_blocked() -> None:
    out = _call(
        MagicMock(),
        _Snap(trading_running=True, actual="RUNNING", source="realtime"),
    )
    assert "TRADING_SCHEDULER_RUNNING" not in out["blockers"]
    assert out["schedulers"]["trading"]["status"] == "RUNNING"
    assert out["schedulers"]["trading"]["ok"] is True
    assert out["dry_run_ready"] is True


def test_scheduler_paused_is_ok_not_blocked() -> None:
    out = _call(
        MagicMock(),
        _Snap(trading_running=False, actual="PAUSED", source="realtime"),
    )
    assert "TRADING_SCHEDULER_RUNNING" not in out["blockers"]
    assert out["schedulers"]["trading"]["status"] == "PAUSED"
    assert out["schedulers"]["trading"]["ok"] is True


def test_scheduler_down_is_blocked() -> None:
    out = _call(
        MagicMock(),
        _Snap(trading_running=None, actual="UNKNOWN", source="unavailable"),
    )
    assert "TRADING_SCHEDULER_DOWN" in out["blockers"]
    assert out["schedulers"]["trading"]["status"] == "DOWN"
    assert out["schedulers"]["trading"]["ok"] is False
    assert out["dry_run_ready"] is False


def test_scheduler_error_is_blocked() -> None:
    out = _call(
        MagicMock(),
        _Snap(trading_running=False, actual="ERROR", source="realtime"),
    )
    assert "TRADING_SCHEDULER_ERROR" in out["blockers"]
    assert out["dry_run_ready"] is False
