"""UPBIT 24/7 Runtime · Outbox Worker 제어 — fixture/mock only.

실 Activation/LIVE/ARM/Worker START 운영 금지. 실 broker CREATE 0.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.live_outbox_worker_runtime import (
    LiveOutboxWorkerRuntime,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.order.outbox_dispatch_safety import (
    OutboxDispatchSafetyError,
    assert_live_outbox_dispatch_safety,
)
from stock_platform.realtime.live_runtime_control import (
    upbit_market_hours_policy,
)
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
)
from stock_platform.trading.upbit_24x7_control import (
    CONFIRM_START_RUNTIME,
    CONFIRM_START_WORKER,
    CONFIRM_STOP_RUNTIME,
    CONFIRM_STOP_WORKER,
    OPERATING_START_SEQUENCE,
    OPERATING_STOP_SEQUENCE,
    REASON_ACTIVATION_INACTIVE,
    REASON_ARM_EXPIRED,
    REASON_CONNECTION_NOT_READY,
    REASON_CREDENTIAL_INVALID,
    REASON_KILL_SWITCH_ACTIVE,
    REASON_LIVE_OFF,
    REASON_OUTBOX_WORKER_NOT_RUNNING,
    REASON_RECOVERY_NOT_READY,
    REASON_UBA_BROKER_MISMATCH,
    RESTART_POLICY,
    UPBIT_MARKET_DATA_24X7,
    WORKER_AUTO_START_POLICY,
    Upbit24x7ControlError,
    combined_control_status,
    evaluate_runtime_run_gates,
    evaluate_runtime_start_gates,
    live_outbox_queue_block_reason,
    start_live_outbox_worker,
    start_upbit_strategy_runtime,
    stop_live_outbox_worker,
    stop_upbit_strategy_runtime,
    runtime_status_for_uba,
)


UBA = 1380
SID = 17483


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uba(**overrides):
    base = dict(
        user_broker_account_id=UBA,
        user_id=61,
        broker_code="UPBIT",
        is_active=True,
        deleted_at=None,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=_now() + timedelta(minutes=10),
        connection_status="CONNECTED",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _session_with_uba(uba):
    session = MagicMock()

    def _get(model, ident):
        name = getattr(model, "__name__", str(model))
        if "UserBrokerAccount" in name:
            return uba
        return None

    session.get.side_effect = _get
    return session


def _gate_ok_patches():
    worker = MagicMock()
    worker.status.return_value = {
        "enabled": True,
        "running": True,
        "auto_start": False,
        "last_error": None,
        "last_run_at": _now().isoformat(),
    }
    return (
        patch(
            "stock_platform.trading.upbit_24x7_control._credential_verified",
            return_value=(True, "VERIFIED"),
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control._kill_active",
            return_value=False,
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control._activation_active",
            return_value={"ok": True, "activation_status": "ACTIVE"},
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control._strategy_ready",
            return_value={"ok": True, "approved": True, "is_active": True},
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.assert_recovery_ready",
            return_value={
                "trading_paused": False,
                "recovery_status": "SUCCESS",
            },
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.assert_risk_account_not_paused",
            return_value={"account_paused": False},
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.live_outbox_queue_block_reason",
            return_value=None,
        ),
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime",
            worker,
        ),
        patch(
            "stock_platform.common.settings.get_settings",
            return_value=SimpleNamespace(
                live_outbox_worker_auto_start=False,
                live_outbox_worker_enabled=True,
                realtime_upbit_24x7_keep_on_krx_close=True,
            ),
        ),
    )


def test_operating_contract_sequence_and_restart_policy() -> None:
    assert OPERATING_START_SEQUENCE == (
        "ACCOUNT_ACTIVATION",
        "LIVE_ON",
        "ARM_ON",
        "OUTBOX_WORKER_START",
        "EXIT_MONITOR_ACTIVE",
        "STRATEGY_RUNTIME_START",
    )
    assert OPERATING_STOP_SEQUENCE[0] == "STRATEGY_RUNTIME_STOP"
    assert "EXIT_MONITOR_STOP" in OPERATING_STOP_SEQUENCE
    assert OPERATING_STOP_SEQUENCE.index("STRATEGY_RUNTIME_STOP") < (
        OPERATING_STOP_SEQUENCE.index("OUTBOX_WORKER_STOP")
    )
    assert WORKER_AUTO_START_POLICY == "OPERATOR_CONTROLLED"
    assert RESTART_POLICY["activation"] == "PERSIST"
    assert RESTART_POLICY["live"] == "REQUIRE_OPERATOR"
    assert RESTART_POLICY["arm"] == "REQUIRE_OPERATOR"
    assert RESTART_POLICY["strategy_runtime"] == "STOP"
    assert RESTART_POLICY["outbox_worker"] == "REQUIRE_OPERATOR"
    assert RESTART_POLICY["exit_monitor"] == "AUTO_RESTORE"
    assert UPBIT_MARKET_DATA_24X7 == "YES"


def test_upbit_market_data_24x7_independent_of_krx() -> None:
    policy = upbit_market_hours_policy()
    assert policy["applies_krx_session"] is False
    assert policy["keep_on_krx_close"] is True


def test_runtime_start_gates_pass() -> None:
    session = _session_with_uba(_uba())
    with _gate_ok_patches()[0], _gate_ok_patches()[1], _gate_ok_patches()[2], \
            _gate_ok_patches()[3], _gate_ok_patches()[4], _gate_ok_patches()[5], \
            _gate_ok_patches()[6], _gate_ok_patches()[7], _gate_ok_patches()[8]:
        result = evaluate_runtime_start_gates(
            session, user_broker_account_id=UBA, strategy_id=SID
        )
    assert result["ok"] is True
    assert result["blockers"] == []
    assert result["checks"]["krx_hours_applied"] is False
    assert result["checks"]["trading_scheduler_required"] is False


def test_runtime_start_blocked_per_invalid_gate() -> None:
    cases = [
        ({"live_order_enabled": False}, REASON_LIVE_OFF),
        ({"live_armed": False}, REASON_ARM_EXPIRED),
        ({"arm_expires_at": _now() - timedelta(minutes=1)}, REASON_ARM_EXPIRED),
        ({"connection_status": "DISCONNECTED"}, REASON_CONNECTION_NOT_READY),
        ({"broker_code": "KIWOOM"}, REASON_UBA_BROKER_MISMATCH),
    ]
    for override, expected in cases:
        session = _session_with_uba(_uba(**override))
        patches = _gate_ok_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
                patches[5], patches[6], patches[7], patches[8]:
            result = evaluate_runtime_start_gates(
                session, user_broker_account_id=UBA, strategy_id=SID
            )
        assert expected in result["blockers"], override


def test_runtime_start_blocked_activation_kill_recovery_credential() -> None:
    session = _session_with_uba(_uba())

    def _run(**replace):
        patches = list(_gate_ok_patches())
        names = [
            "_credential_verified",
            "_kill_active",
            "_activation_active",
        ]
        # rebuild with replacements
        kw = {
            "cred": (True, "VERIFIED"),
            "kill": False,
            "act": {"ok": True, "activation_status": "ACTIVE"},
            "strat": {"ok": True, "approved": True, "is_active": True},
            "rec": {"trading_paused": False, "recovery_status": "SUCCESS"},
        }
        kw.update(replace)
        with (
            patch(
                "stock_platform.trading.upbit_24x7_control._credential_verified",
                return_value=kw["cred"],
            ),
            patch(
                "stock_platform.trading.upbit_24x7_control._kill_active",
                return_value=kw["kill"],
            ),
            patch(
                "stock_platform.trading.upbit_24x7_control._activation_active",
                return_value=kw["act"],
            ),
            patches[3],
            patch(
                "stock_platform.trading.upbit_24x7_control.assert_recovery_ready",
                side_effect=kw.get("rec_exc")
                or (lambda *a, **k: kw["rec"]),
            ),
            patches[5],
            patches[6],
            patches[7],
            patches[8],
        ):
            return evaluate_runtime_start_gates(
                session, user_broker_account_id=UBA, strategy_id=SID
            )

    cred = _run(cred=(False, "INVALID"))
    assert REASON_CREDENTIAL_INVALID in cred["blockers"]

    kill = _run(kill=True)
    assert REASON_KILL_SWITCH_ACTIVE in kill["blockers"]

    act = _run(act={"ok": False})
    # _activation_active returning ok False still doesn't raise — evaluate
    # treats dict ok True only via try. We simulate exception:
    with (
        patch(
            "stock_platform.trading.upbit_24x7_control._credential_verified",
            return_value=(True, "VERIFIED"),
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control._kill_active",
            return_value=False,
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control._activation_active",
            side_effect=PermissionError("no active"),
        ),
        _gate_ok_patches()[3],
        _gate_ok_patches()[4],
        _gate_ok_patches()[5],
        _gate_ok_patches()[6],
        _gate_ok_patches()[7],
        _gate_ok_patches()[8],
    ):
        act2 = evaluate_runtime_start_gates(
            session, user_broker_account_id=UBA, strategy_id=SID
        )
    assert REASON_ACTIVATION_INACTIVE in act2["blockers"]

    rec = _run(
        rec_exc=Upbit24x7ControlError(
            "recovery_not_ready", "FAILED"
        )
    )
    assert REASON_RECOVERY_NOT_READY in rec["blockers"]


def test_runtime_run_gates_pause_on_kill() -> None:
    session = _session_with_uba(_uba())
    with (
        patch(
            "stock_platform.trading.upbit_24x7_control._credential_verified",
            return_value=(True, "VERIFIED"),
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control._kill_active",
            return_value=True,
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control._activation_active",
            return_value={"ok": True},
        ),
        _gate_ok_patches()[3],
        _gate_ok_patches()[4],
        _gate_ok_patches()[5],
        _gate_ok_patches()[6],
        _gate_ok_patches()[7],
        _gate_ok_patches()[8],
        patch(
            "stock_platform.trading.upbit_24x7_control.pause_upbit_runtimes_sync",
            return_value=["scope-1"],
        ) as pause,
    ):
        result = evaluate_runtime_run_gates(
            session, user_broker_account_id=UBA, strategy_id=SID
        )
    assert result["ok"] is False
    assert REASON_KILL_SWITCH_ACTIVE in result["blockers"]
    assert result["runtime_paused"] is True
    assert result["resume_policy"] == "REQUIRE_OPERATOR"
    pause.assert_called_once()


@pytest.mark.asyncio
async def test_runtime_start_stop_idempotent() -> None:
    session = _session_with_uba(_uba())
    running_entry = SimpleNamespace(
        status=RuntimeLifecycleStatus.RUNNING,
        last_heartbeat_at=None,
        updated_at=None,
        last_error=None,
        scope=SimpleNamespace(
            broker_code="UPBIT",
            scope_key="k1",
            user_id=61,
            strategy_id=SID,
        ),
        as_dict=lambda **k: {"status": "RUNNING", "broker_code": "UPBIT"},
    )
    patches = _gate_ok_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patches[8],
        patch(
            "stock_platform.trading.upbit_24x7_control._matching_runtime_entries",
            return_value=[running_entry],
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.runtime_status_for_uba",
            return_value={"status": "RUNNING", "entries": []},
        ),
    ):
        first = await start_upbit_strategy_runtime(
            session,
            user_broker_account_id=UBA,
            strategy_id=SID,
            actor="admin",
            confirmation_text=CONFIRM_START_RUNTIME,
        )
        second = await start_upbit_strategy_runtime(
            session,
            user_broker_account_id=UBA,
            strategy_id=SID,
            actor="admin",
            confirmation_text=CONFIRM_START_RUNTIME,
        )
    assert first["started"] is True
    assert first["reason"] == "ALREADY_RUNNING"
    assert second["idempotent"] is True

    with patch(
        "stock_platform.trading.upbit_24x7_control._matching_runtime_entries",
        return_value=[],
    ), patch(
        "stock_platform.trading.upbit_24x7_control.runtime_status_for_uba",
        return_value={"status": "STOPPED", "entries": []},
    ):
        stopped = await stop_upbit_strategy_runtime(
            session,
            user_broker_account_id=UBA,
            strategy_id=SID,
            confirmation_text=CONFIRM_STOP_RUNTIME,
        )
    assert stopped["stopped"] is True
    assert stopped["reason"] == "ALREADY_STOPPED"
    assert stopped["exit_monitor_untouched"] is True


def test_worker_start_stop_idempotent_and_no_auto_start() -> None:
    runtime = LiveOutboxWorkerRuntime()
    with patch(
        "stock_platform.order.live_outbox_worker_runtime.get_settings",
        return_value=SimpleNamespace(
            live_outbox_worker_enabled=False,
            live_outbox_worker_auto_start=False,
        ),
    ):
        disabled = runtime.start()
    assert disabled["started"] is False
    assert disabled["reason"] == "LIVE_OUTBOX_WORKER_DISABLED"

    stopped = runtime.stop()
    assert stopped["stopped"] is True
    assert stopped["reason"] == "ALREADY_STOPPED"

    mock_rt = MagicMock()
    mock_rt.start.return_value = {
        "started": True,
        "reason": "ALREADY_RUNNING",
        "running": True,
    }
    mock_rt.stop.return_value = {
        "stopped": True,
        "reason": "ALREADY_STOPPED",
        "running": False,
    }
    with patch(
        "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime",
        mock_rt,
    ):
        started = start_live_outbox_worker(
            confirmation_text=CONFIRM_START_WORKER
        )
        again_stop = stop_live_outbox_worker(
            confirmation_text=CONFIRM_STOP_WORKER
        )
    assert started["started"] is True
    assert started["idempotent"] is True
    assert started["dispatch_not_implied"] is True
    assert started["kiwoom_runtime_started"] is False
    assert started["auto_start_policy"] == "OPERATOR_CONTROLLED"
    assert again_stop["stopped"] is True


def test_worker_start_does_not_require_live_arm() -> None:
    mock_rt = MagicMock()
    mock_rt.start.return_value = {"started": True, "running": True}
    with patch(
        "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime",
        mock_rt,
    ):
        result = start_live_outbox_worker(
            confirmation_text=CONFIRM_START_WORKER
        )
    assert result["started"] is True
    assert result["dispatch_not_implied"] is True


def test_worker_down_blocks_live_oes_queue() -> None:
    session = MagicMock()
    session.is_active = True
    svc = OrderExecutionService.__new__(OrderExecutionService)
    svc._session = session
    svc._order_service = MagicMock()
    svc._order_repository = MagicMock()
    svc._outbox_repository = MagicMock()
    svc._sizing_engine = MagicMock()
    svc._resolve_account_ownership = MagicMock(return_value=(None, UBA))
    svc._resolve_size = MagicMock(
        return_value=(Decimal("1"), Decimal("100"), {})
    )

    with (
        patch(
            "stock_platform.common.settings.get_settings",
            return_value=SimpleNamespace(
                live_outbox_worker_enabled=True,
                kiwoom_account_number="",
            ),
        ),
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime.status",
            return_value={"enabled": True, "running": False},
        ),
    ):
        result = svc.submit(
            OrderExecutionCommand(
                account_id=None,
                broker_code="UPBIT",
                exchange_code="UPBIT",
                symbol="KRW-XRP",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                price=Decimal("100"),
                environment="LIVE",
                user_broker_account_id=UBA,
                user_id=61,
                skip_risk_checks=True,
            )
        )
    assert result.allowed is False
    assert result.reason_code == REASON_OUTBOX_WORKER_NOT_RUNNING
    svc._order_service.create.assert_not_called()


def test_paper_oes_not_blocked_by_worker_down() -> None:
    session = MagicMock()
    session.is_active = True
    svc = OrderExecutionService.__new__(OrderExecutionService)
    svc._session = session
    svc._order_service = MagicMock()
    svc._order_repository = MagicMock()
    svc._outbox_repository = MagicMock()
    svc._sizing_engine = MagicMock()
    svc._resolve_account_ownership = MagicMock(return_value=(1, None))
    svc._resolve_size = MagicMock(
        return_value=(Decimal("1"), Decimal("100"), {})
    )
    svc._order_service.create.side_effect = AssertionError("paper stub")

    with patch(
        "stock_platform.common.settings.get_settings",
        return_value=SimpleNamespace(
            live_outbox_worker_enabled=True,
            kiwoom_account_number="123",
        ),
    ), patch(
        "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime.status",
        return_value={"enabled": True, "running": False},
    ):
        paper_reason = live_outbox_queue_block_reason()
        try:
            result = svc.submit(
                OrderExecutionCommand(
                    account_id=1,
                    broker_code="PAPER",
                    exchange_code="UPBIT",
                    symbol="KRW-XRP",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=Decimal("1"),
                    price=Decimal("100"),
                    environment="PAPER",
                    skip_risk_checks=True,
                )
            )
        except AssertionError:
            result = SimpleNamespace(reason_code="STUB")
    assert paper_reason == REASON_OUTBOX_WORKER_NOT_RUNNING
    assert result.reason_code != REASON_OUTBOX_WORKER_NOT_RUNNING


def test_krx_closed_does_not_block_upbit_gates() -> None:
    session = _session_with_uba(_uba())
    patches = _gate_ok_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patches[8],
        patch(
            "stock_platform.realtime.live_runtime_control.should_keep_upbit_on_krx_close",
            return_value=True,
        ),
    ):
        result = evaluate_runtime_start_gates(
            session, user_broker_account_id=UBA, strategy_id=SID
        )
    assert result["ok"] is True
    assert "KRX_CLOSED" not in result["blockers"]
    assert result["checks"]["market_hours"]["applies_krx_session"] is False


def test_exit_monitor_independent_of_strategy_runtime() -> None:
    from stock_platform.trading.upbit_24x7_control import (
        exit_monitor_status,
        runtime_status_for_uba,
    )

    runtime = runtime_status_for_uba(
        user_broker_account_id=UBA, strategy_id=SID
    )
    assert runtime["status"] == "STOPPED"
    assert runtime["independent_of_exit_monitor"] is True
    monitor = exit_monitor_status()
    assert monitor["independent_of_strategy_runtime"] is True
    assert monitor["orders_via_oes_only"] is True
    assert monitor["broker_submit_requires_oes_fail_closed"] is True


def test_exit_monitor_sl_still_goes_to_oes_when_runtime_stopped() -> None:
    from stock_platform.position.exit_monitor import (
        ManagedPosition,
        PositionExitMonitorService,
    )

    session = MagicMock()
    oes = MagicMock()
    oes.submit.return_value = SimpleNamespace(
        allowed=True,
        order_id=99,
        reason_code="QUEUED",
        quantity=Decimal("10"),
    )
    with (
        patch(
            "stock_platform.position.exit_monitor.OrderExecutionService",
            return_value=oes,
        ),
        patch(
            "stock_platform.position.exit_monitor_live.has_blocking_live_exit_sell",
            return_value=False,
        ),
    ):
        monitor = PositionExitMonitorService(session)
        pos = ManagedPosition(
            account_id=0,
            exchange_code="UPBIT",
            symbol="KRW-XRP",
            quantity=Decimal("10"),
            entry_price=Decimal("100"),
            current_price=Decimal("90"),
            highest_price=Decimal("100"),
            stop_loss_price=Decimal("95"),
            take_profit_price=Decimal("110"),
            user_broker_account_id=UBA,
            environment="LIVE",
            broker_code="UPBIT",
            owner_user_id=61,
        )
        actions = monitor.evaluate_and_exit([pos], skip_risk_checks=False)
    runtime = runtime_status_for_uba(
        user_broker_account_id=UBA, strategy_id=SID
    )
    assert runtime["status"] == "STOPPED"
    assert oes.submit.call_count == 1
    assert actions[0].submitted is True
    assert actions[0].order_id == 99


def test_queued_restart_fail_closed_no_broker_create() -> None:
    from stock_platform.operation.live_health_gate import LiveHealthBlockedError

    session = MagicMock()
    uba = _uba(live_order_enabled=False, live_armed=False)
    session.get.return_value = uba
    with pytest.raises((OutboxDispatchSafetyError, LiveHealthBlockedError)):
        assert_live_outbox_dispatch_safety(
            session,
            {
                "environment": "LIVE",
                "user_broker_account_id": UBA,
                "broker_code": "UPBIT",
            },
        )


def test_kiwoom_isolation_runtime_start_gate() -> None:
    session = _session_with_uba(_uba(broker_code="KIWOOM"))
    patches = _gate_ok_patches()
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
            patches[5], patches[6], patches[7], patches[8]:
        result = evaluate_runtime_start_gates(
            session, user_broker_account_id=1381, strategy_id=SID
        )
    assert REASON_UBA_BROKER_MISMATCH in result["blockers"]


def test_combined_status_quiet_stop_visible() -> None:
    session = _session_with_uba(
        _uba(live_order_enabled=False, live_armed=False)
    )
    with (
        patch(
            "stock_platform.trading.upbit_24x7_control._activation_active",
            side_effect=PermissionError("none"),
        ),
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime.status",
            return_value={
                "enabled": True,
                "running": False,
                "auto_start": False,
                "last_error": None,
            },
        ),
    ):
        payload = combined_control_status(
            session, user_broker_account_id=UBA, strategy_id=SID
        )
    assert payload["activation"] == "INACTIVE"
    assert payload["live"] == "OFF"
    assert payload["arm"] == "EXPIRED"
    assert payload["strategy_runtime"] in {"STOPPED", "PAUSED", "ERROR"}
    assert payload["outbox_worker"] == "STOPPED"
    assert payload["start_all_forbidden"] is True
    assert payload["trading_scheduler_required"] is False


def test_health_24x7_additive() -> None:
    from stock_platform.trading.upbit_24x7_control import (
        build_24x7_ops_health,
    )

    payload = build_24x7_ops_health()
    assert "strategy_runtime" in payload
    assert "live_outbox_worker" in payload
    assert "live_exit_monitor" in payload
    # reliability heartbeats가 last_evaluated_at를 읽도록 필드 유지
    assert "last_evaluated_at" in payload["live_exit_monitor"]
    assert payload["upbit_market_data_24x7"] == "YES"
    assert payload["worker_running_not_dispatch_allowed"] is True


def test_startup_policy_still_operator_restore_for_live_arm() -> None:
    from stock_platform.operation.startup_runtime_policy import (
        RuntimeStartupPolicy,
    )

    assert hasattr(RuntimeStartupPolicy, "_force_live_off")
    assert hasattr(RuntimeStartupPolicy, "_force_arm_off")
    from stock_platform.common.settings import get_settings

    assert get_settings().live_outbox_worker_auto_start is False


def test_confirmation_required() -> None:
    with pytest.raises(Upbit24x7ControlError) as exc:
        start_live_outbox_worker(confirmation_text="go")
    assert exc.value.code == "CONFIRMATION_REQUIRED"


def test_scope_heartbeat_field_exists() -> None:
    from stock_platform.strategy_deployment.runtime_manager import (
        ScopedRuntimeEntry,
    )
    from stock_platform.strategy_deployment.runtime_models import (
        LoadedStrategyRuntime,
    )

    scope = StrategyRuntimeScope(
        user_id=61,
        account_kind=AccountKind.USER_BROKER,
        account_id=UBA,
        strategy_id=SID,
        strategy_version="v1",
        market_type="CRYPTO",
        broker_code="UPBIT",
        strategy_code="UPBIT_MA_XRP_V1",
        market_code="UPBIT",
    )
    runtime = LoadedStrategyRuntime(
        deployment_id=1,
        strategy_code="UPBIT_MA_XRP_V1",
        market_code="UPBIT",
        symbol="KRW-XRP",
        parameter_payload={},
        loaded_at=_now(),
        user_id=61,
        account_id=None,
        user_broker_account_id=UBA,
        strategy_id=SID,
        strategy_version="v1",
        market_type="CRYPTO",
        scope_key=scope.scope_key,
        broker_code="UPBIT",
        account_kind="USER_BROKER",
    )
    entry = ScopedRuntimeEntry(
        scope=scope,
        runtime=runtime,
        strategy=object(),
        status=RuntimeLifecycleStatus.STOPPED,
    )
    data = entry.as_dict()
    assert "last_heartbeat_at" in data
    assert data["status"] == "STOPPED"
