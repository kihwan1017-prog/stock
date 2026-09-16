"""STEP 10-2 Scheduler/Runtime state persistence and startup restore tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.operation.runtime_control_repository import (
    RuntimeControlConflictError,
    RuntimeControlRepository,
)
from stock_platform.trading.trading_scheduler_control import (
    get_trading_scheduler_desired_state,
    hydrate_trading_scheduler_control,
    reset_trading_scheduler_control_for_tests,
)
from stock_platform.trading.trading_scheduler_control_service import (
    TradingSchedulerControlError,
    TradingSchedulerControlService,
)


@pytest.fixture(autouse=True)
def _reset_control():
    reset_trading_scheduler_control_for_tests()
    yield
    reset_trading_scheduler_control_for_tests()


def test_desired_state_defaults_pause_after_reset() -> None:
    assert get_trading_scheduler_desired_state() == "PAUSE"


def test_hydrate_from_db_restores_run() -> None:
    hydrate_trading_scheduler_control(
        desired_state="RUN",
        actor="admin",
        reason="persisted",
        version=3,
        persisted=True,
    )
    assert get_trading_scheduler_desired_state() == "RUN"


def test_startup_restore_skips_when_desired_pause() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        desired_state="PAUSE",
        requested_by="admin",
        requested_reason="pause",
        correlation_id="c1",
        updated_at=datetime.now(timezone.utc),
        version=1,
        blocked_reason=None,
        startup_restore_attempted=False,
        startup_restore_result=None,
        last_started_at=None,
        last_paused_at=None,
        control_id=1,
    )
    repo = MagicMock()
    repo.get_trading_scheduler_row.return_value = row
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.RuntimeControlRepository",
            return_value=repo,
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_trading_scheduler"
        ) as sched,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.emit_live_safety_audit"
        ),
    ):
        sched.scheduler.running = False
        result = TradingSchedulerControlService(
            session
        ).attempt_startup_restore(
            process_instance_id="pid-test",
            migration_at_head=True,
        )
    assert result["result"] == "SKIPPED_DESIRED_PAUSE"
    assert result["restored"] is False
    sched.start.assert_not_called()


def test_startup_restore_run_when_safe() -> None:
    """재시작 시 desired=RUN이어도 자동 RUN 금지 — FORCED_PAUSE."""
    session = MagicMock()
    row = SimpleNamespace(
        desired_state="RUN",
        requested_by="admin",
        requested_reason="run",
        correlation_id="c1",
        updated_at=datetime.now(timezone.utc),
        version=2,
        blocked_reason=None,
        startup_restore_attempted=False,
        startup_restore_result=None,
        last_started_at=None,
        last_paused_at=None,
        control_id=1,
    )
    repo = MagicMock()
    repo.get_trading_scheduler_row.return_value = row
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.RuntimeControlRepository",
            return_value=repo,
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_trading_scheduler"
        ) as sched,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.set_trading_scheduler_desired_state"
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.hydrate_trading_scheduler_control"
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.emit_live_safety_audit"
        ),
    ):
        sched.scheduler.running = False
        result = TradingSchedulerControlService(
            session
        ).attempt_startup_restore(
            process_instance_id="pid-test",
            migration_at_head=True,
        )
    assert result["restored"] is False
    assert result["result"] == "FORCED_PAUSE"
    assert result["blocked_reason"] == "OPERATOR_SEQUENCE_REQUIRED"
    assert result["actual_state"] == "PAUSED"
    sched.start.assert_not_called()


def test_startup_restore_blocked_kill_switch() -> None:
    """Kill Switch와 무관하게 startup은 FORCED_PAUSE (운영자 순서 강제)."""
    session = MagicMock()
    row = SimpleNamespace(
        desired_state="RUN",
        control_id=1,
    )
    repo = MagicMock()
    repo.get_trading_scheduler_row.return_value = row
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.RuntimeControlRepository",
            return_value=repo,
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_trading_scheduler"
        ) as sched,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.set_trading_scheduler_desired_state"
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.hydrate_trading_scheduler_control"
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.emit_live_safety_audit"
        ),
    ):
        sched.scheduler.running = False
        result = TradingSchedulerControlService(
            session
        ).attempt_startup_restore(
            process_instance_id="pid-test",
            migration_at_head=True,
        )
    assert result["result"] == "FORCED_PAUSE"
    assert result["blocked_reason"] == "OPERATOR_SEQUENCE_REQUIRED"
    sched.start.assert_not_called()


def test_startup_restore_blocked_submission_unknown() -> None:
    session = MagicMock()
    svc = TradingSchedulerControlService(session)
    with (
        patch.object(
            svc,
            "evaluate_startup_restore_conditions",
            return_value=(False, "SUBMISSION_UNKNOWN_PRESENT"),
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.RuntimeControlRepository"
        ) as repo_cls,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_trading_scheduler"
        ) as sched,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.set_trading_scheduler_desired_state"
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.hydrate_trading_scheduler_control"
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.emit_live_safety_audit"
        ),
    ):
        repo_cls.return_value.get_trading_scheduler_row.return_value = (
            SimpleNamespace(desired_state="RUN", control_id=1)
        )
        sched.scheduler.running = False
        result = svc.attempt_startup_restore(
            process_instance_id="pid",
            migration_at_head=True,
        )
    assert result["result"] == "FORCED_PAUSE"
    assert result["blocked_reason"] == "SUBMISSION_UNKNOWN_PRESENT"


def test_live_arm_forced_off_on_startup_phase1() -> None:
    import asyncio

    session = MagicMock()
    uba_live = SimpleNamespace(
        user_broker_account_id=58,
        user_id=7,
        broker_code="UPBIT",
        live_order_enabled=True,
        live_armed=False,
        arm_expires_at=None,
        updated_at=None,
    )
    uba_arm = SimpleNamespace(
        user_broker_account_id=59,
        user_id=7,
        broker_code="UPBIT",
        live_order_enabled=False,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        updated_at=None,
    )
    row = SimpleNamespace(
        desired_state="PAUSE",
        requested_by="admin",
        requested_reason="r",
        correlation_id="c",
        updated_at=datetime.now(timezone.utc),
        version=1,
        blocked_reason=None,
        startup_restore_attempted=False,
        startup_restore_result=None,
        last_started_at=None,
        last_paused_at=None,
    )

    async def _run():
        with (
            patch(
                "stock_platform.operation.startup_runtime_policy.migration_at_head",
                return_value=True,
            ),
            patch(
                "stock_platform.operation.startup_runtime_policy.RuntimeControlRepository"
            ) as repo_cls,
            patch(
                "stock_platform.operation.startup_runtime_policy.LiveArmService"
            ) as arm_cls,
            patch(
                "stock_platform.operation.startup_runtime_policy.emit_live_safety_audit"
            ),
        ):
            repo_cls.return_value.get_trading_scheduler_row.return_value = row
            session.scalars.side_effect = [
                iter([uba_live]),
                iter([uba_arm]),
            ]
            arm_cls.return_value.disarm.return_value = {}
            session.refresh = MagicMock()
            from stock_platform.operation.startup_runtime_policy import (
                RuntimeStartupPolicy,
            )

            return await RuntimeStartupPolicy(session).apply_phase1()

    result = asyncio.run(_run())
    assert result["live_forced_off_count"] == 1
    assert result["arm_forced_off_count"] == 1


@pytest.mark.asyncio
async def test_strategy_runtime_forced_idle_phase2() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.operation.startup_runtime_policy.dynamic_strategy_runtime_manager"
        ) as mgr,
        patch(
            "stock_platform.operation.startup_runtime_policy.realtime_execution_runner"
        ) as ex,
        patch(
            "stock_platform.operation.startup_runtime_policy.realtime_strategy_runner"
        ) as st,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.TradingSchedulerControlService",
        ) as svc_cls,
        patch(
            "stock_platform.operation.startup_runtime_policy.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.operation.startup_runtime_policy.migration_at_head",
            return_value=True,
        ),
    ):
        mgr.pause_all = AsyncMock(return_value=2)
        ex.stop = AsyncMock()
        st.stop = AsyncMock()
        svc_cls.return_value.attempt_startup_restore.return_value = {
            "restored": False,
            "result": "SKIPPED_DESIRED_PAUSE",
        }
        from stock_platform.operation.startup_runtime_policy import (
            RuntimeStartupPolicy,
        )

        result = await RuntimeStartupPolicy(session).apply_phase2()
    assert result["strategy_runtime_paused_count"] == 2
    mgr.pause_all.assert_awaited_once()


def test_start_persists_desired_run() -> None:
    session = MagicMock()
    db_row = SimpleNamespace(
        desired_state="RUN",
        requested_by="admin",
        requested_reason="R",
        correlation_id="c1",
        updated_at=datetime.now(timezone.utc),
        version=2,
    )
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.RuntimeControlRepository"
        ) as repo_cls,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_trading_scheduler"
        ) as sched,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_strategy_runner"
        ) as st,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_execution_runner"
        ) as ex,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.emit_live_safety_audit"
        ),
    ):
        repo_cls.return_value.update_trading_scheduler_desired.return_value = (
            db_row
        )
        repo_cls.return_value.touch_heartbeat = MagicMock()
        sched.scheduler.running = False
        sched.scheduler.get_jobs.return_value = []
        st.status.return_value = {"running": False, "active_scopes": 0}
        ex.status.return_value = {"running": False}
        session.get.return_value = None
        TradingSchedulerControlService(session).start(
            actor="admin",
            reason="start",
            correlation_id="c1",
            user_broker_account_id=58,
            enforce_gates=False,
        )
    repo_cls.return_value.update_trading_scheduler_desired.assert_called_once()
    sched.start.assert_called_once()


def test_pause_idempotent_already_paused() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_trading_scheduler"
        ) as sched,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_strategy_runner"
        ) as st,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_execution_runner"
        ) as ex,
    ):
        sched.scheduler.running = False
        sched.scheduler.get_jobs.return_value = []
        st.status.return_value = {"running": False, "active_scopes": 0}
        ex.status.return_value = {"running": False}
        result = TradingSchedulerControlService(session).pause(
            actor="admin",
            reason="pause",
            correlation_id="c1",
        )
    assert result["already_paused"] is True


def test_optimistic_lock_conflict() -> None:
    from stock_platform.trading.trading_scheduler_control import (
        set_trading_scheduler_desired_state,
    )

    session = MagicMock()
    repo = MagicMock()
    repo.update_trading_scheduler_desired.side_effect = (
        RuntimeControlConflictError()
    )
    set_trading_scheduler_desired_state("RUN", actor="a", reason="r")
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.RuntimeControlRepository",
            return_value=repo,
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_trading_scheduler"
        ) as sched,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_strategy_runner"
        ) as st,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_execution_runner"
        ) as ex,
    ):
        sched.scheduler.running = True
        sched.scheduler.get_jobs.return_value = []
        st.status.return_value = {"running": False, "active_scopes": 0}
        ex.status.return_value = {"running": False}
        with pytest.raises(TradingSchedulerControlError) as ei:
            TradingSchedulerControlService(session).pause(
                actor="admin",
                reason="pause",
                correlation_id="c1",
            )
    assert ei.value.code == "version_conflict"


def test_scheduler_run_does_not_call_create_order() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.RuntimeControlRepository"
        ) as repo_cls,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_trading_scheduler"
        ) as sched,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_strategy_runner"
        ) as st,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_execution_runner"
        ) as ex,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.broker.upbit.order_client.UpbitOrderRestClient.create_order"
        ) as create_order,
    ):
        repo_cls.return_value.update_trading_scheduler_desired.return_value = (
            SimpleNamespace(
                desired_state="RUN",
                requested_by="a",
                requested_reason="r",
                correlation_id="c",
                updated_at=datetime.now(timezone.utc),
                version=1,
            )
        )
        repo_cls.return_value.touch_heartbeat = MagicMock()
        sched.scheduler.running = False
        sched.scheduler.get_jobs.return_value = []
        st.status.return_value = {"running": False, "active_scopes": 0}
        ex.status.return_value = {"running": False}
        session.get.return_value = None
        TradingSchedulerControlService(session).start(
            actor="admin",
            reason="r",
            correlation_id="c",
            user_broker_account_id=1,
            enforce_gates=False,
        )
    create_order.assert_not_called()


def test_step10_1_post_fill_regression_import() -> None:
    """STEP 10-1 post-fill regression imports still resolve."""

    from stock_platform.broker.upbit.fill_sync_service import (
        UpbitFillSyncService,
    )
    from stock_platform.broker.upbit.order_status import (
        normalize_upbit_order_status,
    )

    assert UpbitFillSyncService is not None
    assert normalize_upbit_order_status is not None


def test_step10_2_revision_head() -> None:
    from tests.migration_helpers import (
        assert_revision_exists,
        assert_revision_is_ancestor_of_head,
    )

    assert_revision_exists("w3d4e5f6a7b8")
    assert_revision_exists("x4e5f6a7b8c9")
    assert_revision_exists("y5f6a7b8c9d0")
    assert_revision_exists("z6a7b8c9d0e1")
    assert_revision_exists("aa1b2c3d4e5f")
    assert_revision_is_ancestor_of_head("ae5f6a7b8c9d")
