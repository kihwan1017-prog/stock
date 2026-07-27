"""STEP 8-11A — Recovery Scheduler status / Dashboard alignment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.broker.recovery_scheduler import BrokerRecoveryScheduler
from stock_platform.operation.ops_monitoring.service import (
    OpsMonitoringDashboardService,
)
from stock_platform.operation.ops_monitoring.status import compute_overall_status
from stock_platform.risk_engine.kill_switch_models import KillSwitchStatus


def test_recovery_desired_uses_recovery_scheduler_enabled() -> None:
    session = MagicMock()
    svc = OpsMonitoringDashboardService(session)
    settings = SimpleNamespace(
        recovery_scheduler_enabled=True,
        upbit_live_track_enabled=True,
        post_fill_verify_enabled=True,
    )
    with (
        patch(
            "stock_platform.operation.ops_monitoring.service.get_settings",
            return_value=settings,
        ),
        patch(
            "stock_platform.operation.ops_monitoring.service.collect_scheduler_readiness",
            return_value=SimpleNamespace(
                trading_scheduler_desired_state="PAUSE",
                trading_scheduler_actual_state="PAUSED",
                trading_running=False,
                tracking_desired_state="RUNNING",
                tracking_scheduler_running=True,
                post_fill_desired_state="RUNNING",
                post_fill_scheduler_running=True,
                snapshot_stale=False,
                to_dict=lambda: {},
            ),
        ),
        patch(
            "stock_platform.broker.recovery_scheduler.broker_recovery_scheduler.status",
            return_value={
                "running": True,
                "enabled": True,
                "desired_state": "RUNNING",
                "actual_state": "RUNNING",
                "stale": False,
                "consecutive_failures": 0,
                "job_count": 5,
            },
        ),
    ):
        bundle = svc._scheduler_bundle()
    assert bundle["recovery"]["desired_state"] == "RUNNING"
    assert bundle["recovery"]["actual_state"] == "RUNNING"
    assert bundle["recovery"]["running"] is True


def test_recovery_cooldown_not_treated_as_stopped_warning() -> None:
    overall = compute_overall_status({"errors": [], "warnings": []})
    assert overall == "HEALTHY"
    session = MagicMock()
    svc = OpsMonitoringDashboardService(session)
    with (
        patch.object(
            svc,
            "_scheduler_bundle",
            return_value={
                "trading": {
                    "desired_state": "PAUSE",
                    "actual_state": "PAUSED",
                    "running": False,
                },
                "tracking": {"actual_state": "RUNNING", "running": True},
                "post_fill": {"actual_state": "RUNNING", "running": True},
                "recovery": {
                    "desired_state": "RUNNING",
                    "actual_state": "COOLDOWN",
                    "running": True,
                    "enabled": True,
                },
            },
        ),
        patch(
            "stock_platform.operation.ops_monitoring.service.measure_db_latency_ms",
            lambda: ("UP", 1.0, None),
        ),
        patch.object(
            svc,
            "_broker_overview",
            return_value={
                "UPBIT": {"status": "HEALTHY"},
                "KIWOOM": {"status": "NOT_CONFIGURED"},
            },
        ),
        patch.object(
            svc,
            "_runtime_counts",
            return_value={
                "running_count": 0,
                "paused_count": 0,
                "error_count": 0,
            },
        ),
        patch.object(
            svc,
            "_alert_counts",
            return_value={"critical": 0, "warning": 0, "manual_review": 0},
        ),
        patch.object(svc, "_active_uba_kill_count", return_value=0),
        patch(
            "stock_platform.operation.ops_monitoring.service.KillSwitchService",
            lambda _s: SimpleNamespace(
                get_state=lambda: SimpleNamespace(
                    status=KillSwitchStatus.INACTIVE
                )
            ),
        ),
    ):
        out = svc.overview()
    assert "RECOVERY_SCHEDULER_STOPPED" not in out["warning_codes"]
    assert out["overall_status"] == "HEALTHY"


def test_recovery_stopped_when_enabled_is_warning() -> None:
    session = MagicMock()
    svc = OpsMonitoringDashboardService(session)
    with (
        patch.object(
            svc,
            "_scheduler_bundle",
            return_value={
                "trading": {
                    "desired_state": "PAUSE",
                    "actual_state": "PAUSED",
                    "running": False,
                },
                "tracking": {"actual_state": "RUNNING", "running": True},
                "post_fill": {"actual_state": "RUNNING", "running": True},
                "recovery": {
                    "desired_state": "RUNNING",
                    "actual_state": "STOPPED",
                    "running": False,
                    "enabled": True,
                },
            },
        ),
        patch(
            "stock_platform.operation.ops_monitoring.service.measure_db_latency_ms",
            lambda: ("UP", 1.0, None),
        ),
        patch.object(
            svc,
            "_broker_overview",
            return_value={
                "UPBIT": {"status": "HEALTHY"},
                "KIWOOM": {"status": "NOT_CONFIGURED"},
            },
        ),
        patch.object(
            svc,
            "_runtime_counts",
            return_value={
                "running_count": 0,
                "paused_count": 0,
                "error_count": 0,
            },
        ),
        patch.object(
            svc,
            "_alert_counts",
            return_value={"critical": 0, "warning": 0, "manual_review": 0},
        ),
        patch.object(svc, "_active_uba_kill_count", return_value=0),
        patch(
            "stock_platform.operation.ops_monitoring.service.KillSwitchService",
            lambda _s: SimpleNamespace(
                get_state=lambda: SimpleNamespace(
                    status=KillSwitchStatus.INACTIVE
                )
            ),
        ),
    ):
        out = svc.overview()
    assert "RECOVERY_SCHEDULER_STOPPED" in out["warning_codes"]
    assert out["overall_status"] == "WARNING"


def test_recovery_status_disabled_state(monkeypatch) -> None:
    sched = BrokerRecoveryScheduler()
    monkeypatch.setattr(
        "stock_platform.broker.recovery_scheduler.get_settings",
        lambda: SimpleNamespace(
            recovery_scheduler_enabled=False,
            recovery_scheduler_startup_cooldown_seconds=120,
            scheduler_timezone="Asia/Seoul",
        ),
    )
    monkeypatch.setattr(
        "stock_platform.broker.recovery_scheduler.get_session_factory",
        lambda: (lambda: MagicMock(close=lambda: None)),
    )
    with patch(
        "stock_platform.broker.recovery_scheduler.BrokerRecoverySchedulerService",
        lambda _s: SimpleNamespace(list_jobs=lambda: []),
    ):
        st = sched.status()
    assert st["enabled"] is False
    assert st["desired_state"] == "STOPPED"
    assert st["actual_state"] == "DISABLED"


def test_recovery_status_cooldown_state(monkeypatch) -> None:
    sched = BrokerRecoveryScheduler()
    monkeypatch.setattr(
        "stock_platform.broker.recovery_scheduler.get_settings",
        lambda: SimpleNamespace(
            recovery_scheduler_enabled=True,
            recovery_scheduler_startup_cooldown_seconds=120,
            scheduler_timezone="Asia/Seoul",
        ),
    )
    monkeypatch.setattr(
        "stock_platform.broker.recovery_scheduler.get_session_factory",
        lambda: (lambda: MagicMock(close=lambda: None)),
    )
    fake_scheduler = MagicMock()
    fake_scheduler.running = True
    fake_scheduler.get_jobs.return_value = []
    fake_scheduler.timezone = "Asia/Seoul"
    sched._scheduler = fake_scheduler
    with (
        patch(
            "stock_platform.broker.recovery_scheduler.BrokerRecoverySchedulerService",
            lambda _s: SimpleNamespace(list_jobs=lambda: []),
        ),
        patch(
            "stock_platform.broker.recovery_runtime.broker_recovery_manager",
            SimpleNamespace(
                _startup_finished_at=datetime.now(timezone.utc)
                - timedelta(seconds=10)
            ),
        ),
    ):
        st = sched.status()
    assert st["desired_state"] == "RUNNING"
    assert st["actual_state"] == "COOLDOWN"
    assert st["reason_code"] == "STARTUP_COOLDOWN"
    assert st["cooldown_active"] is True


def test_recovery_job_not_registered_is_stopped(monkeypatch) -> None:
    sched = BrokerRecoveryScheduler()
    monkeypatch.setattr(
        "stock_platform.broker.recovery_scheduler.get_settings",
        lambda: SimpleNamespace(
            recovery_scheduler_enabled=True,
            recovery_scheduler_startup_cooldown_seconds=0,
            scheduler_timezone="Asia/Seoul",
        ),
    )
    monkeypatch.setattr(
        "stock_platform.broker.recovery_scheduler.get_session_factory",
        lambda: (lambda: MagicMock(close=lambda: None)),
    )
    fake_scheduler = MagicMock()
    fake_scheduler.running = False
    fake_scheduler.get_jobs.return_value = []
    fake_scheduler.timezone = "Asia/Seoul"
    sched._scheduler = fake_scheduler
    sched._configured = True
    with patch(
        "stock_platform.broker.recovery_scheduler.BrokerRecoverySchedulerService",
        lambda _s: SimpleNamespace(list_jobs=lambda: []),
    ):
        st = sched.status()
    assert st["actual_state"] == "STOPPED"
    assert st["desired_state"] == "RUNNING"


def test_disabled_desired_not_running_warning() -> None:
    session = MagicMock()
    svc = OpsMonitoringDashboardService(session)
    with (
        patch.object(
            svc,
            "_scheduler_bundle",
            return_value={
                "trading": {
                    "desired_state": "PAUSE",
                    "actual_state": "PAUSED",
                    "running": False,
                },
                "tracking": {"actual_state": "RUNNING", "running": True},
                "post_fill": {"actual_state": "RUNNING", "running": True},
                "recovery": {
                    "desired_state": "STOPPED",
                    "actual_state": "DISABLED",
                    "running": False,
                    "enabled": False,
                },
            },
        ),
        patch(
            "stock_platform.operation.ops_monitoring.service.measure_db_latency_ms",
            lambda: ("UP", 1.0, None),
        ),
        patch.object(
            svc,
            "_broker_overview",
            return_value={
                "UPBIT": {"status": "HEALTHY"},
                "KIWOOM": {"status": "NOT_CONFIGURED"},
            },
        ),
        patch.object(
            svc,
            "_runtime_counts",
            return_value={
                "running_count": 0,
                "paused_count": 0,
                "error_count": 0,
            },
        ),
        patch.object(
            svc,
            "_alert_counts",
            return_value={"critical": 0, "warning": 0, "manual_review": 0},
        ),
        patch.object(svc, "_active_uba_kill_count", return_value=0),
        patch(
            "stock_platform.operation.ops_monitoring.service.KillSwitchService",
            lambda _s: SimpleNamespace(
                get_state=lambda: SimpleNamespace(
                    status=KillSwitchStatus.INACTIVE
                )
            ),
        ),
    ):
        out = svc.overview()
    assert "RECOVERY_SCHEDULER_STOPPED" not in out["warning_codes"]


def test_lifecycle_starts_recovery_before_lifecycle_gate() -> None:
    src = Path("src/stock_platform/api/lifecycle.py").read_text(encoding="utf-8")
    assert "broker_recovery_scheduler.start()" in src
    # Recovery start가 lifecycle_scheduler_enabled 게이트보다 앞에 있어야 함
    start_idx = src.index("broker_recovery_scheduler.start()")
    gate_idx = src.index("if not settings.lifecycle_scheduler_enabled")
    assert start_idx < gate_idx
