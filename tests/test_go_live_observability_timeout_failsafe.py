"""GO-LIVE observability timeout fail-safe — targeted tests A-H.

실 Broker / Activation / LIVE / ARM / Runner START 없음.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.live_config_gate import evaluate_live_flag_consistency
from stock_platform.broker.upbit.rules import REASON_UPBIT_MIN_NOTIONAL_NOT_MET
from stock_platform.operation.controlled_live_shutdown import (
    STATUS_SUCCESS,
    STATUS_UNKNOWN,
    run_shutdown_steps,
    shutdown_sequence_names,
)
from stock_platform.operation.live_observation import (
    ACTION_CONTINUE,
    ACTION_ROLLBACK,
    CriticalSafetySnapshot,
    decide_observation_action,
)
from stock_platform.operation.observability_http import (
    CRITICAL_MUTATION_TIMEOUT,
    HTTP_OK,
    OBSERVABILITY_TIMEOUT,
    classify_http_result,
    is_timeout_exception,
    observability_timeout_should_rollback,
    request_json,
)
from stock_platform.order.models import OrderStatus
from stock_platform.order.pre_persist_exit_gate import evaluate_pre_persist_exit_gate
from stock_platform.risk_engine.exit_risk import is_order_outstanding_for_sell
from stock_platform.trading.upbit_24x7_control import combined_control_status


HELD_XRP = Decimal("3.44827587")
DUST_PRICE = Decimal("1404")
SELLABLE_PRICE = Decimal("1450")
UBA1380 = 1380
SYMBOL = "KRW-XRP"


def _critical_ok(**overrides) -> CriticalSafetySnapshot:
    base = dict(
        live_on=True,
        arm_on=True,
        kill_off=True,
        recovery_success=True,
        connected=True,
        credential_verified=True,
        account_paused=False,
        trading_paused=False,
        kiwoom_live_off=True,
        runner_error=None,
        first_fail=None,
    )
    base.update(overrides)
    return CriticalSafetySnapshot(**base)


def test_a_observability_get_timeout_does_not_rollback() -> None:
    assert observability_timeout_should_rollback() is False
    cls = classify_http_result(
        http_status=0, body={"detail": "timeout"}, kind="observability"
    )
    assert cls == OBSERVABILITY_TIMEOUT
    decision = decide_observation_action(
        observability_class=cls,
        critical=_critical_ok(),
    )
    assert decision.action == ACTION_CONTINUE
    assert decision.observability == "OBSERVABILITY_DEGRADED"
    assert decision.reason == OBSERVABILITY_TIMEOUT


def test_b_critical_safety_fail_is_fail_closed() -> None:
    snap = _critical_ok(kill_off=False, first_fail="KILL_ON")
    decision = decide_observation_action(
        observability_class=HTTP_OK,
        critical=snap,
    )
    assert decision.action == ACTION_ROLLBACK
    assert decision.reason == "KILL_ON"


def test_b_live_unexpectedly_off_is_fail_closed() -> None:
    snap = _critical_ok(live_on=False)
    decision = decide_observation_action(
        observability_class=OBSERVABILITY_TIMEOUT,
        critical=snap,
    )
    assert decision.action == ACTION_ROLLBACK


def test_c_rollback_runner_stop_timeout_continues() -> None:
    calls: list[str] = []

    def runner_stop():
        calls.append("runner_stop")
        return 0, {"detail": "timeout"}

    def runtime_stop():
        calls.append("runtime_stop")
        return 200, {"stopped": True}

    results = run_shutdown_steps(
        [
            ("runner_stop", runner_stop),
            ("runtime_stop", runtime_stop),
            ("worker_stop", lambda: (200, {"stopped": True})),
            ("arm_off", lambda: (200, {"ok": True})),
            ("live_off", lambda: (200, {"ok": True})),
            ("activation_disable", lambda: (200, {"ok": True})),
        ]
    )
    assert [r.name for r in results] == [
        "runner_stop",
        "runtime_stop",
        "worker_stop",
        "arm_off",
        "live_off",
        "activation_disable",
    ]
    assert results[0].status == STATUS_UNKNOWN
    assert results[1].status == STATUS_SUCCESS
    assert calls == ["runner_stop", "runtime_stop"]


def test_d_rollback_runtime_stop_timeout_continues_to_activation() -> None:
    order: list[str] = []

    def timed_out(name: str):
        def _fn():
            order.append(name)
            raise TimeoutError("timed out")

        return _fn

    def ok(name: str):
        def _fn():
            order.append(name)
            return 200, {"ok": True}

        return _fn

    results = run_shutdown_steps(
        [
            ("runner_stop", ok("runner_stop")),
            ("runtime_stop", timed_out("runtime_stop")),
            ("exit_monitor_stop", ok("exit_monitor_stop")),
            ("worker_stop", ok("worker_stop")),
            ("arm_off", ok("arm_off")),
            ("live_off", ok("live_off")),
            ("activation_disable", ok("activation_disable")),
        ]
    )
    assert order == list(shutdown_sequence_names())
    assert results[1].status == STATUS_UNKNOWN
    assert results[-1].name == "activation_disable"
    assert results[-1].status == STATUS_SUCCESS


def test_e_normal_24x7_status_get_shape() -> None:
    uba = SimpleNamespace(
        live_order_enabled=False,
        live_armed=False,
        arm_expires_at=None,
        broker_code="UPBIT",
    )
    session = MagicMock()
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.upbit_24x7_control._activation_active",
            return_value={"ok": False},
        ),
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime"
        ) as worker,
        patch(
            "stock_platform.trading.upbit_24x7_control.runtime_status_for_uba",
            return_value={"status": "STOPPED", "entries": [], "last_error": None,
                          "last_heartbeat_at": None, "independent_of_exit_monitor": True},
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.exit_monitor_status",
            return_value={"status": "STOPPED", "last_error": None},
        ),
    ):
        worker.status.return_value = {"running": False, "last_error": None}
        payload = combined_control_status(
            session, user_broker_account_id=1380, strategy_id=17483
        )
    assert payload["user_broker_account_id"] == 1380
    assert payload["live"] == "OFF"
    assert payload["activation"] == "INACTIVE"
    assert payload["outbox_worker"] == "STOPPED"
    assert payload["start_all_forbidden"] is True
    assert "worker" in payload


def test_f_min_notional_regression_blocks_persist() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    pos = SimpleNamespace(symbol=SYMBOL, exchange_code="UPBIT", quantity=HELD_XRP)
    with patch(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
    ) as Repo:
        Repo.return_value.get_active_by_uba.return_value = (object(), [pos])
        reason = evaluate_pre_persist_exit_gate(
            session,
            side="SELL",
            symbol=SYMBOL,
            exchange_code="UPBIT",
            quantity=HELD_XRP,
            price=DUST_PRICE,
            order_type="LIMIT",
            broker_code="UPBIT",
            environment="LIVE",
            user_broker_account_id=UBA1380,
            paper_account_id=None,
        )
    assert reason == REASON_UPBIT_MIN_NOTIONAL_NOT_MET


def test_g_duplicate_exit_regression() -> None:
    row = SimpleNamespace(
        status_code=OrderStatus.PENDING.value,
        order_quantity=HELD_XRP,
        remaining_quantity=HELD_XRP,
        filled_quantity=Decimal("0"),
        broker_order_id=None,
        reason_code=None,
        metadata_payload={},
        user_broker_account_id=UBA1380,
        broker_code="UPBIT",
        symbol=SYMBOL,
        side_code="SELL",
    )
    outbox = SimpleNamespace(
        status_code="AMBIGUOUS",
        confirmation_status="BROKER_CONFIRMATION_REQUIRED",
        dispatch_intent_at=datetime(2026, 8, 18, 23, 17, 12, tzinfo=timezone.utc),
        last_error="RETRY_BLOCKED_AFTER_INTENT:minimum",
        manual_review_reason=None,
    )
    assert is_order_outstanding_for_sell(row, outbox) is True
    cancelled = SimpleNamespace(
        status_code=OrderStatus.CANCELLED.value,
        order_quantity=HELD_XRP,
        remaining_quantity=HELD_XRP,
        filled_quantity=Decimal("0"),
        broker_order_id=None,
        reason_code=None,
        metadata_payload={},
        user_broker_account_id=UBA1380,
        broker_code="UPBIT",
        symbol=SYMBOL,
        side_code="SELL",
    )
    resolved = SimpleNamespace(
        status_code="FAILED",
        confirmation_status="CONFIRMED_ABSENT",
        dispatch_intent_at=datetime(2026, 8, 18, 23, 17, 12, tzinfo=timezone.utc),
        last_error="UNSUBMITTED_LIVE_ORDER_RETIRED:BROKER_NOT_REACHED_LOCAL_VALIDATION_FAILURE:x",
        manual_review_reason=None,
    )
    assert is_order_outstanding_for_sell(cancelled, resolved) is False


def test_h_kiwoom_isolation_regression() -> None:
    flags = SimpleNamespace(
        global_live_order_enabled=True,
        kiwoom_live_order_enabled=True,
        kiwoom_use_mock=True,
        upbit_live_order_enabled=True,
        upbit_use_mock=False,
    )
    with patch(
        "stock_platform.broker.live_config_gate.get_settings", return_value=flags
    ):
        upbit = evaluate_live_flag_consistency(broker_code="UPBIT")
        kiwoom = evaluate_live_flag_consistency(broker_code="KIWOOM")
    assert upbit.code == "UPBIT_FLAGS_OK"
    assert upbit.allowed is True
    assert kiwoom.code == "LIVE_MOCK_CONFLICT"


def test_timeout_exception_hierarchy() -> None:
    assert is_timeout_exception(TimeoutError("timed out")) is True
    from urllib.error import URLError

    assert is_timeout_exception(URLError(TimeoutError("timed out"))) is True
    crit = classify_http_result(
        http_status=0, body={"detail": "timeout"}, kind="critical_mutation"
    )
    assert crit == CRITICAL_MUTATION_TIMEOUT


def test_e2_lightweight_status_helpers_are_in_memory() -> None:
    from stock_platform.trading.upbit_24x7_control import (
        exit_monitor_status,
        runtime_status_for_uba,
    )

    exit_payload = exit_monitor_status()
    runtime_payload = runtime_status_for_uba(
        user_broker_account_id=1380, strategy_id=17483
    )
    assert "status" in exit_payload
    assert "status" in runtime_payload
    assert exit_payload["independent_of_strategy_runtime"] is True


def test_request_json_swallows_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(
        "stock_platform.operation.observability_http.urlopen", boom
    )
    http, body = request_json("GET", "http://127.0.0.1:8000/x", timeout=0.1)
    assert http == 0
    assert body["detail"] == "timeout"
    assert (
        classify_http_result(http_status=http, body=body, kind="observability")
        == OBSERVABILITY_TIMEOUT
    )
