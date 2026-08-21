"""Unattended stack restore + readiness gates — focused (실주문 0)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.strategy_deployment.runtime_scope import (
    RuntimeLifecycleStatus,
)
from stock_platform.trading.autotrading_master_gate import (
    STATUS_BLOCKED,
    evaluate_uba_autotrading_ready,
)
from stock_platform.trading.upbit_unattended_stack_restore import (
    evaluate_stack_restore_gates,
    restore_upbit_trading_stack,
)


def _uba(**kwargs):
    base = dict(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        is_active=True,
        deleted_at=None,
        live_order_enabled=True,
        live_armed=True,
        live_approved_at=datetime.now(timezone.utc),
        user_id=61,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _approved_link_session(session: MagicMock) -> None:
    """승인 active strategy link 1건."""

    link = SimpleNamespace(
        account_strategy_link_id=1,
        strategy_id=17483,
        is_active=True,
        user_id=61,
    )
    strategy = SimpleNamespace(
        strategy_id=17483,
        is_active=True,
        approved_at=datetime.now(timezone.utc),
        market_type="CRYPTO",
        strategy_code="MA",
        name="MA",
        parameter_payload={"symbol": "KRW-MET2"},
    )

    def _get(model, pk):
        name = getattr(model, "__name__", str(model))
        if "UserBroker" in name:
            return _uba()
        if "StrategyDefinition" in name:
            return strategy
        return None

    session.get.side_effect = _get
    session.scalars.return_value = [link]
    session.scalar.return_value = 0


def test_readiness_blocks_paused_runtime_when_live_on() -> None:
    session = MagicMock()
    _approved_link_session(session)

    with (
        patch(
            "stock_platform.trading.strategy_runtime_authorization.evaluate_strategy_runtime_authorization",
            return_value={"ok": True, "mode": "LIVE_APPROVED"},
        ),
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as act,
        patch(
            "stock_platform.trading.upbit_live_pipeline_readiness.UpbitLivePipelineReadinessService"
        ) as pipe,
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime"
        ) as worker,
        patch(
            "stock_platform.strategy_deployment.runtime_manager.dynamic_strategy_runtime_manager"
        ) as mgr,
        patch(
            "stock_platform.trading.upbit_24x7_control.combined_control_status",
            return_value={
                "strategy_runtime": "PAUSED",
                "outbox_worker": "RUNNING",
                "exit_monitor": "RUNNING",
            },
        ),
        patch(
            "stock_platform.risk_engine.user_risk_service.UserRiskSettingService"
        ) as risk,
    ):
        act.return_value.require_active.return_value = SimpleNamespace(
            live_trading_transition_id=1,
            activation_status="PENDING",
            enabled=True,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            scope="ACCOUNT",
            broker_code="UPBIT",
        )
        pipe.return_value.evaluate.return_value = {
            "ops_ready": True,
            "blockers": [],
            "warnings": [],
            "checks": {
                "credential": {"ok": True},
                "quote_ws": {
                    "ok": True,
                    "running": True,
                    "connected": True,
                    "symbols": ["KRW-MET2"],
                    "last_received_at": datetime.now(timezone.utc).isoformat(),
                },
                "hub_status": {
                    "hub_status": "CONNECTED",
                    "ok": True,
                    "running": True,
                },
            },
        }
        worker.status.return_value = {"enabled": True, "running": True}
        mgr.status.return_value = {
            "runtimes": [
                {
                    "status": "PAUSED",
                    "account_id": 1380,
                    "account_kind": "USER_BROKER",
                    "user_broker_account_id": 1380,
                }
            ]
        }
        risk.return_value.resolve.return_value = SimpleNamespace(
            daily_order_limit=10,
            max_order_amount=100000,
            daily_loss_limit=None,
            daily_submit_limit=None,
            daily_filled_entry_limit=None,
        )
        out = evaluate_uba_autotrading_ready(
            session, user_broker_account_id=1380
        )

    assert out["status"] == STATUS_BLOCKED
    assert "STRATEGY_RUNTIME_NOT_RUNNING" in out["blockers"]


def test_readiness_blocks_stopped_live_worker_when_live_on() -> None:
    session = MagicMock()
    _approved_link_session(session)

    with (
        patch(
            "stock_platform.trading.strategy_runtime_authorization.evaluate_strategy_runtime_authorization",
            return_value={"ok": True, "mode": "LIVE_APPROVED"},
        ),
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as act,
        patch(
            "stock_platform.trading.upbit_live_pipeline_readiness.UpbitLivePipelineReadinessService"
        ) as pipe,
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime"
        ) as worker,
        patch(
            "stock_platform.strategy_deployment.runtime_manager.dynamic_strategy_runtime_manager"
        ) as mgr,
        patch(
            "stock_platform.trading.upbit_24x7_control.combined_control_status",
            return_value={
                "strategy_runtime": "RUNNING",
                "outbox_worker": "STOPPED",
                "exit_monitor": "RUNNING",
            },
        ),
        patch(
            "stock_platform.risk_engine.user_risk_service.UserRiskSettingService"
        ) as risk,
    ):
        act.return_value.require_active.return_value = SimpleNamespace(
            live_trading_transition_id=1,
            activation_status="PENDING",
            enabled=True,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            scope="ACCOUNT",
            broker_code="UPBIT",
        )
        pipe.return_value.evaluate.return_value = {
            "ops_ready": True,
            "blockers": [],
            "warnings": [],
            "checks": {
                "credential": {"ok": True},
                "quote_ws": {
                    "ok": True,
                    "running": True,
                    "connected": True,
                    "symbols": ["KRW-MET2"],
                    "last_received_at": datetime.now(timezone.utc).isoformat(),
                },
                "hub_status": {
                    "hub_status": "CONNECTED",
                    "ok": True,
                    "running": True,
                },
            },
        }
        worker.status.return_value = {"enabled": True, "running": False}
        mgr.status.return_value = {
            "runtimes": [
                {
                    "status": "RUNNING",
                    "account_id": 1380,
                    "account_kind": "USER_BROKER",
                    "user_broker_account_id": 1380,
                }
            ]
        }
        risk.return_value.resolve.return_value = SimpleNamespace(
            daily_order_limit=10,
            max_order_amount=100000,
            daily_loss_limit=None,
            daily_submit_limit=None,
            daily_filled_entry_limit=None,
        )
        out = evaluate_uba_autotrading_ready(
            session, user_broker_account_id=1380
        )

    assert out["status"] == STATUS_BLOCKED
    assert "LIVE_OUTBOX_WORKER_NOT_RUNNING" in out["blockers"]


def test_stack_gates_fail_without_lease() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    with patch(
        "stock_platform.trading.upbit_unattended_stack_restore.LiveUnattendedAuthorizationService"
    ) as svc:
        svc.return_value.get_active.return_value = None
        svc.return_value.evaluate_enable_gates.return_value = {
            "ok": True,
            "blockers": [],
            "execution_env": "REAL",
        }
        with patch(
            "stock_platform.operation.upbit_full_market.service.UpbitFullMarketAssignmentService"
        ) as asg:
            asg.return_value.status_dict.return_value = {
                "portfolio_enabled": True,
                "strategy_id": 17483,
            }
            out = evaluate_stack_restore_gates(
                session, user_broker_account_id=1380
            )
    assert out["ok"] is False
    assert "NO_ACTIVE_LEASE" in out["blockers"]


def test_stack_gates_fail_when_kill_on() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    lease = SimpleNamespace(status_code="ACTIVE")
    with patch(
        "stock_platform.trading.upbit_unattended_stack_restore.LiveUnattendedAuthorizationService"
    ) as svc:
        svc.return_value.get_active.return_value = lease
        svc.return_value.evaluate_enable_gates.return_value = {
            "ok": False,
            "blockers": ["KILL_SWITCH_ACTIVE"],
            "execution_env": "REAL",
        }
        with patch(
            "stock_platform.operation.upbit_full_market.service.UpbitFullMarketAssignmentService"
        ) as asg:
            asg.return_value.status_dict.return_value = {
                "portfolio_enabled": True,
                "strategy_id": 17483,
            }
            out = evaluate_stack_restore_gates(
                session, user_broker_account_id=1380
            )
    assert out["ok"] is False
    assert "KILL_SWITCH_ACTIVE" in out["blockers"]


def test_stack_gates_fail_on_conflict() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    lease = SimpleNamespace(status_code="ACTIVE")
    with patch(
        "stock_platform.trading.upbit_unattended_stack_restore.LiveUnattendedAuthorizationService"
    ) as svc:
        svc.return_value.get_active.return_value = lease
        svc.return_value.evaluate_enable_gates.return_value = {
            "ok": False,
            "blockers": ["CONFLICT_HIGH_1"],
            "execution_env": "REAL",
        }
        with patch(
            "stock_platform.operation.upbit_full_market.service.UpbitFullMarketAssignmentService"
        ) as asg:
            asg.return_value.status_dict.return_value = {
                "portfolio_enabled": True,
                "strategy_id": 17483,
            }
            out = evaluate_stack_restore_gates(
                session, user_broker_account_id=1380
            )
    assert out["ok"] is False
    assert "CONFLICT_HIGH_1" in out["blockers"]


@pytest.mark.asyncio
async def test_stack_restore_resumes_runtime_and_starts_worker() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    paused = SimpleNamespace(
        status=RuntimeLifecycleStatus.PAUSED,
        scope=SimpleNamespace(
            scope_key="user:61|uba:1380|sid:17483",
            broker_code="UPBIT",
        ),
    )

    with (
        patch(
            "stock_platform.trading.upbit_unattended_stack_restore.evaluate_stack_restore_gates",
            return_value={
                "ok": True,
                "blockers": [],
                "checks": {
                    "portfolio": {
                        "portfolio_enabled": True,
                        "strategy_id": 17483,
                    }
                },
            },
        ),
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime"
        ) as worker,
        patch(
            "stock_platform.strategy_deployment.runtime_manager.dynamic_strategy_runtime_manager"
        ) as mgr,
        patch(
            "stock_platform.trading.upbit_24x7_control.evaluate_runtime_start_gates",
            return_value={"ok": True, "blockers": []},
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.runtime_status_for_uba",
            return_value={"status": "RUNNING"},
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.exit_monitor_status",
            return_value={"status": "RUNNING"},
        ),
    ):
        worker.status.return_value = {"enabled": True, "running": False}
        worker.start.return_value = {
            "started": True,
            "reason": "STARTED",
            "running": True,
        }
        mgr.list_entries.return_value = [paused]
        mgr.resume_runtime = AsyncMock(return_value=paused)

        out = await restore_upbit_trading_stack(
            session, user_broker_account_id=1380
        )

    assert out["restored"] is True
    worker.start.assert_called_once()
    mgr.resume_runtime.assert_awaited_once_with(
        "user:61|uba:1380|sid:17483"
    )
    assert out["detail"]["runtime"]["reason"] == "RESUMED"
    assert out["detail"]["exit"]["reason"] == "ALREADY_RUNNING_OR_OK"


@pytest.mark.asyncio
async def test_stack_restore_skips_duplicate_worker() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    running = SimpleNamespace(
        status=RuntimeLifecycleStatus.RUNNING,
        scope=SimpleNamespace(
            scope_key="sk",
            broker_code="UPBIT",
        ),
    )
    with (
        patch(
            "stock_platform.trading.upbit_unattended_stack_restore.evaluate_stack_restore_gates",
            return_value={
                "ok": True,
                "blockers": [],
                "checks": {
                    "portfolio": {
                        "portfolio_enabled": True,
                        "strategy_id": 17483,
                    }
                },
            },
        ),
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime"
        ) as worker,
        patch(
            "stock_platform.strategy_deployment.runtime_manager.dynamic_strategy_runtime_manager"
        ) as mgr,
        patch(
            "stock_platform.trading.upbit_24x7_control.evaluate_runtime_start_gates",
            return_value={"ok": True, "blockers": []},
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.runtime_status_for_uba",
            return_value={"status": "RUNNING"},
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.exit_monitor_status",
            return_value={"status": "RUNNING"},
        ),
    ):
        worker.status.return_value = {"enabled": True, "running": True}
        mgr.list_entries.return_value = [running]
        out = await restore_upbit_trading_stack(
            session, user_broker_account_id=1380
        )
    assert out["restored"] is True
    worker.start.assert_not_called()
    assert out["detail"]["worker"]["idempotent"] is True
    assert out["detail"]["runtime"]["reason"] == "ALREADY_RUNNING"


@pytest.mark.asyncio
async def test_stack_restore_no_op_when_gates_fail() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.trading.upbit_unattended_stack_restore.evaluate_stack_restore_gates",
        return_value={
            "ok": False,
            "blockers": ["NO_ACTIVE_LEASE"],
            "checks": {},
        },
    ):
        out = await restore_upbit_trading_stack(
            session, user_broker_account_id=1380
        )
    assert out["restored"] is False
    assert out["reason"] == "STACK_GATES_FAILED"


def test_restore_from_active_lease_accepts_restore_stack_flag() -> None:
    """restore_stack=False면 스케줄 없이 LIVE/ARM만 (startup 전용 경로)."""

    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedAuthorizationService,
    )

    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    with patch.object(svc, "get_active", return_value=None):
        out = svc.restore_from_active_lease(1380, restore_stack=False)
    assert out == {"restored": False, "reason": "NO_ACTIVE_LEASE"}
