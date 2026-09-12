"""LIVE Outbox dispatch fail-closed — broker CREATE 직전 재검증.

fixture/mock only. 실 UPBIT/KIWOOM API · Outbox worker START 금지.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.models import (
    BrokerOrderResult,
    BrokerOrderStatus,
)
from stock_platform.order.outbox_dispatch_safety import (
    AUDIT_EVENT_DISPATCH_SAFETY_REJECTED,
    REASON_ACCOUNT_PAUSED,
    REASON_ACTIVATION_INACTIVE,
    REASON_ARM_EXPIRED,
    REASON_CONNECTION_NOT_READY,
    REASON_CREDENTIAL_NOT_READY,
    REASON_KILL_SWITCH_ACTIVE,
    REASON_RECOVERY_NOT_READY,
    REASON_TRADING_PAUSED,
    OutboxDispatchSafetyError,
    assert_live_outbox_dispatch_safety,
    emit_outbox_dispatch_safety_rejection,
)
from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.order.outbox_worker import OrderOutboxWorker


class CountingAdapter:
    """broker CREATE/CANCEL/AMEND 횟수 spy — 실 HTTP 없음."""

    def __init__(self) -> None:
        self.submit_order_calls = 0
        self.cancel_order_calls = 0
        self.amend_order_calls = 0

    def submit_order(self, request, idempotency_key=None):
        self.submit_order_calls += 1
        return BrokerOrderResult(
            accepted=True,
            status=BrokerOrderStatus.ACCEPTED,
            broker_order_id="mock-1",
            submitted_at=datetime.now(timezone.utc),
        )

    def cancel_order(self, *a, **k):
        self.cancel_order_calls += 1
        raise AssertionError("cancel_order must not run")

    def replace_order(self, *a, **k):
        self.amend_order_calls += 1
        raise AssertionError("replace_order must not run")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uba(
    *,
    uba_id: int = 1380,
    broker: str = "UPBIT",
    user_id: int = 61,
    live: bool = True,
    armed: bool = True,
    conn: str = "CONNECTED",
    active: bool = True,
):
    return SimpleNamespace(
        user_broker_account_id=uba_id,
        user_id=user_id,
        broker_code=broker,
        is_active=active,
        deleted_at=None,
        live_order_enabled=live,
        live_armed=armed,
        connection_status=conn,
        arm_expires_at=_now() + timedelta(minutes=10),
    )


def _payload(
    *,
    uba_id: int = 1380,
    broker: str = "UPBIT",
    owner_id: int = 61,
    environment: str = "LIVE",
    order_id: int = 20,
) -> dict[str, Any]:
    return {
        "environment": environment,
        "broker_code": broker,
        "user_broker_account_id": uba_id,
        "owner_user_id": owner_id,
        "order_id": order_id,
        "client_order_id": "CLIENT-1",
        "account_id": None,
        "exchange_code": "UPBIT" if broker == "UPBIT" else "KRX",
        "symbol": "KRW-BTC" if broker == "UPBIT" else "005930",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "1",
        "price": "100",
        "time_in_force": "DAY",
    }


def _cred(
    *,
    broker: str = "UPBIT",
    verified: bool = True,
    active: bool = True,
    revoked=None,
):
    return SimpleNamespace(
        is_active=active,
        broker_code=broker,
        verification_status="VERIFIED" if verified else "PENDING",
        revoked_at=revoked,
        expires_at=None,
    )


def _live_pass_ctx(
    session: MagicMock,
    uba,
    *,
    cred=None,
    kill_on: bool = False,
    recovery_error: tuple[str, str] | None = None,
    account_paused: bool = False,
    conn_error: bool = False,
    activation_error: str | None = None,
    arm_expired: bool = False,
):
    """공통 LIVE pass/fail fixture. 실 Activation/ARM POST 없음."""

    session.get.return_value = uba
    cred_entity = (
        cred
        if cred is not None
        else _cred(broker=str(uba.broker_code))
    )

    class _Vault:
        def __init__(self, *_a, **_k):
            pass

        def get_active_entity(self, *_a, **_k):
            return cred_entity

    def _recovery(_s, _id, *, raise_error):
        if recovery_error is not None:
            raise raise_error(recovery_error[0], recovery_error[1])
        return {"trading_paused": False, "recovery_status": "SUCCESS"}

    def _risk(_s, _uba, *, raise_error):
        if account_paused:
            raise raise_error("account_paused", "paused")
        return {"account_paused": False, "arm_ttl_seconds": 300}

    def _conn(_uba, *, raise_error):
        if conn_error:
            raise raise_error(
                "connection_not_connected",
                "connection_status must be CONNECTED",
            )

    act_side = None
    if activation_error:
        act_side = PermissionError(activation_error)

    class _KS:
        GLOBAL_SCOPE = "GLOBAL"

        def __init__(self, *_a, **_k):
            pass

        def is_active_for_scopes(self, *_a, **_k):
            return kill_on

    require_kw: dict[str, Any] = (
        {"side_effect": act_side}
        if act_side is not None
        else {"return_value": object()}
    )
    arm_patch = patch(
        "stock_platform.trading.live_arm_service.LiveArmService"
    )
    return (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard.require_active",
            **require_kw,
        ),
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService",
            _KS,
        ),
        patch(
            "stock_platform.order.outbox_dispatch_safety.assert_recovery_ready",
            side_effect=_recovery,
        ),
        patch(
            "stock_platform.order.outbox_dispatch_safety.assert_risk_account_not_paused",
            side_effect=_risk,
        ),
        patch(
            "stock_platform.order.outbox_dispatch_safety.assert_uba_connection_ready",
            side_effect=_conn,
        ),
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService",
            _Vault,
        ),
        patch(
            "stock_platform.order.outbox_dispatcher.get_settings_safe_identifier_enabled",
            return_value=False,
        ),
        arm_patch,
        arm_expired,
    )


def _enter_live_pass(session, uba, **kwargs):
    raw = _live_pass_ctx(session, uba, **kwargs)
    arm_expired = raw[-1]
    patchers = list(raw[:-1])
    started: list[Any] = []
    try:
        mocks = []
        for p in patchers:
            mocks.append(p.start())
            started.append(p)
        arm_mock = mocks[-1]
        arm_mock.return_value.expire_if_needed.return_value = arm_expired
        return started, mocks
    except Exception:
        for p in reversed(started):
            p.stop()
        raise


def _exit_patches(patches) -> None:
    for p in reversed(list(patches)):
        p.stop()


# ---------------------------------------------------------------------------
# Gate unit: race A–H + success + paper
# ---------------------------------------------------------------------------


def test_paper_skips_live_dispatch_gates() -> None:
    session = MagicMock()
    assert_live_outbox_dispatch_safety(
        session, _payload(environment="PAPER"), outbox_id=1
    )
    session.get.assert_not_called()


def test_a_kill_switch_blocks_create() -> None:
    session = MagicMock()
    uba = _uba()
    patches, _ = _enter_live_pass(session, uba, kill_on=True)
    try:
        with pytest.raises(OutboxDispatchSafetyError) as ei:
            assert_live_outbox_dispatch_safety(
                session, _payload(), outbox_id=10
            )
        assert ei.value.reason_code == REASON_KILL_SWITCH_ACTIVE
    finally:
        _exit_patches(patches)


def test_b_trading_paused_blocks_create() -> None:
    session = MagicMock()
    uba = _uba()
    patches, _ = _enter_live_pass(
        session,
        uba,
        recovery_error=("trading_paused", "paused"),
    )
    try:
        with pytest.raises(OutboxDispatchSafetyError) as ei:
            assert_live_outbox_dispatch_safety(
                session, _payload(), outbox_id=10
            )
        assert ei.value.reason_code == REASON_TRADING_PAUSED
    finally:
        _exit_patches(patches)


def test_c_recovery_failed_blocks_create() -> None:
    session = MagicMock()
    uba = _uba()
    patches, _ = _enter_live_pass(
        session,
        uba,
        recovery_error=("recovery_not_ready", "FAILED"),
    )
    try:
        with pytest.raises(OutboxDispatchSafetyError) as ei:
            assert_live_outbox_dispatch_safety(
                session, _payload(), outbox_id=10
            )
        assert ei.value.reason_code == REASON_RECOVERY_NOT_READY
    finally:
        _exit_patches(patches)


def test_d_credential_invalid_blocks_create() -> None:
    session = MagicMock()
    uba = _uba()
    patches, _ = _enter_live_pass(
        session, uba, cred=_cred(verified=False)
    )
    try:
        with pytest.raises(OutboxDispatchSafetyError) as ei:
            assert_live_outbox_dispatch_safety(
                session, _payload(), outbox_id=10
            )
        assert ei.value.reason_code == REASON_CREDENTIAL_NOT_READY
    finally:
        _exit_patches(patches)


def test_e_disconnected_blocks_create() -> None:
    session = MagicMock()
    uba = _uba(conn="DISCONNECTED")
    patches, _ = _enter_live_pass(session, uba, conn_error=True)
    try:
        with pytest.raises(OutboxDispatchSafetyError) as ei:
            assert_live_outbox_dispatch_safety(
                session, _payload(), outbox_id=10
            )
        assert ei.value.reason_code == REASON_CONNECTION_NOT_READY
    finally:
        _exit_patches(patches)


def test_f_account_paused_blocks_create() -> None:
    session = MagicMock()
    uba = _uba()
    patches, _ = _enter_live_pass(session, uba, account_paused=True)
    try:
        with pytest.raises(OutboxDispatchSafetyError) as ei:
            assert_live_outbox_dispatch_safety(
                session, _payload(), outbox_id=10
            )
        assert ei.value.reason_code == REASON_ACCOUNT_PAUSED
    finally:
        _exit_patches(patches)


def test_g_activation_expiry_blocks_create() -> None:
    session = MagicMock()
    uba = _uba()
    patches, _ = _enter_live_pass(
        session,
        uba,
        activation_error="No active live trading transition approval",
    )
    try:
        with pytest.raises(OutboxDispatchSafetyError) as ei:
            assert_live_outbox_dispatch_safety(
                session, _payload(), outbox_id=10
            )
        assert ei.value.reason_code == REASON_ACTIVATION_INACTIVE
        assert "active live trading" in str(ei.value)
    finally:
        _exit_patches(patches)


def test_h_arm_expiry_blocks_create() -> None:
    session = MagicMock()
    uba = _uba(live=True, armed=True)
    patches, _ = _enter_live_pass(session, uba, arm_expired=True)
    try:
        with pytest.raises(OutboxDispatchSafetyError) as ei:
            assert_live_outbox_dispatch_safety(
                session, _payload(), outbox_id=None
            )
        assert ei.value.reason_code == REASON_ARM_EXPIRED
    finally:
        _exit_patches(patches)


def test_success_path_does_not_raise() -> None:
    session = MagicMock()
    uba = _uba()
    patches, _ = _enter_live_pass(session, uba)
    try:
        assert_live_outbox_dispatch_safety(
            session, _payload(), outbox_id=10
        )
    finally:
        _exit_patches(patches)


# ---------------------------------------------------------------------------
# Dispatcher: submit 직전 게이트 + adapter count
# ---------------------------------------------------------------------------


def test_dispatcher_failure_submit_cancel_amend_zero() -> None:
    adapter = CountingAdapter()
    session = MagicMock()
    uba = _uba()
    patches, _ = _enter_live_pass(session, uba, kill_on=True)
    try:
        with pytest.raises(OutboxDispatchSafetyError) as ei:
            with patch(
                "stock_platform.order.outbox_dispatcher.resolve_outbox_adapter",
                return_value=adapter,
            ):
                OrderOutboxDispatcher(adapter, session=session).dispatch(
                    event_type="SUBMIT_ORDER",
                    payload=_payload(),
                    idempotency_key="k1",
                    session=session,
                    outbox_id=10,
                )
        assert ei.value.reason_code == REASON_KILL_SWITCH_ACTIVE
    finally:
        _exit_patches(patches)
    assert adapter.submit_order_calls == 0
    assert adapter.cancel_order_calls == 0
    assert adapter.amend_order_calls == 0


def test_dispatcher_success_submit_exactly_once() -> None:
    adapter = CountingAdapter()
    session = MagicMock()
    uba = _uba()
    patches, _ = _enter_live_pass(session, uba)
    try:
        with patch(
            "stock_platform.order.outbox_dispatcher.resolve_outbox_adapter",
            return_value=adapter,
        ):
            result = OrderOutboxDispatcher(adapter, session=session).dispatch(
                event_type="SUBMIT_ORDER",
                payload=_payload(),
                idempotency_key="k-ok",
                session=session,
                outbox_id=10,
            )
    finally:
        _exit_patches(patches)
    assert result["accepted"] is True
    assert adapter.submit_order_calls == 1
    assert adapter.cancel_order_calls == 0
    assert adapter.amend_order_calls == 0


def test_dispatcher_duplicate_broker_id_skips_submit() -> None:
    adapter = CountingAdapter()
    payload = _payload(environment="PAPER")
    payload["broker_order_id"] = "already-1"
    with patch(
        "stock_platform.order.outbox_dispatcher.resolve_outbox_adapter",
        return_value=adapter,
    ):
        result = OrderOutboxDispatcher(adapter).dispatch(
            event_type="SUBMIT_ORDER",
            payload=payload,
            idempotency_key="dup",
        )
    assert result.get("duplicate_suppressed") is True
    assert adapter.submit_order_calls == 0


def test_paper_dispatcher_not_blocked_by_live_gates() -> None:
    adapter = CountingAdapter()
    with patch(
        "stock_platform.order.outbox_dispatcher.resolve_outbox_adapter",
        return_value=adapter,
    ):
        result = OrderOutboxDispatcher(adapter).dispatch(
            event_type="SUBMIT_ORDER",
            payload=_payload(environment="PAPER"),
            idempotency_key="paper-1",
        )
    assert result["accepted"] is True
    assert adapter.submit_order_calls == 1


# ---------------------------------------------------------------------------
# Worker: FAILED terminal + stale retry 금지 + adapter 0
# ---------------------------------------------------------------------------


def _entity(payload: dict[str, Any] | None = None):
    return SimpleNamespace(
        outbox_id=10,
        order_id=20,
        event_type="SUBMIT_ORDER",
        idempotency_key="idemp-1",
        payload_json=payload or _payload(),
        status_code=OutboxStatus.PROCESSING.value,
        fencing_token=1,
        retry_count=0,
        max_retry_count=5,
        dispatch_intent_at=None,
        last_error=None,
    )


def _run_claimed_with_safety_error(
    adapter: CountingAdapter,
    *,
    reason: str,
) -> tuple[Any, MagicMock]:
    entity = _entity()
    session = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = False
    factory = MagicMock(return_value=cm)
    repo = MagicMock()
    repo.get.return_value = entity
    worker = OrderOutboxWorker(
        session_factory=factory,
        dispatcher=OrderOutboxDispatcher(adapter),
        worker_id="test-worker",
    )
    err = OutboxDispatchSafetyError(reason, reason)
    with (
        patch(
            "stock_platform.order.outbox_worker.OrderOutboxRepository",
            return_value=repo,
        ),
        patch(
            "stock_platform.order.outbox_worker.PostgreSqlIdempotencyRepository"
        ),
        patch.object(
            OrderOutboxWorker,
            "_order_already_has_broker_id",
            return_value=False,
        ),
        patch.object(
            OrderOutboxWorker,
            "_assert_live_dispatch_allowed",
            side_effect=err,
        ),
        patch.object(OrderOutboxWorker, "_finalize_smoke_one_shot_if_needed"),
        patch.object(OrderOutboxWorker, "_fail_open_order"),
        patch(
            "stock_platform.order.outbox_worker.emit_outbox_dispatch_safety_rejection"
        ) as audit,
    ):
        summary = worker._run_claimed([(10, 1)])
    return summary, repo, audit


def test_worker_kill_marks_failed_no_broker_call() -> None:
    adapter = CountingAdapter()
    summary, repo, audit = _run_claimed_with_safety_error(
        adapter, reason=REASON_KILL_SWITCH_ACTIVE
    )
    assert adapter.submit_order_calls == 0
    assert adapter.cancel_order_calls == 0
    assert adapter.amend_order_calls == 0
    assert summary.failed == 1
    assert summary.retried == 0
    repo.mark_failed.assert_called_once()
    repo.mark_retry.assert_not_called()
    audit.assert_called_once()


def test_worker_stale_retry_not_automatic() -> None:
    """FAILED 는 claim 대상이 아님 — 안전 복구 후에도 자동 재전송 금지."""

    adapter = CountingAdapter()
    _run_claimed_with_safety_error(
        adapter, reason=REASON_TRADING_PAUSED
    )
    assert OutboxStatus.FAILED.value not in {
        OutboxStatus.PENDING.value,
        OutboxStatus.RETRY.value,
    }
    # 두 번째 polling: claim 0 → dispatcher 미호출
    session = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = False
    factory = MagicMock(return_value=cm)
    repo = MagicMock()
    repo.claim_one.return_value = None
    worker = OrderOutboxWorker(
        session_factory=factory,
        dispatcher=OrderOutboxDispatcher(adapter),
        worker_id="test-worker",
    )
    with patch(
        "stock_platform.order.outbox_worker.OrderOutboxRepository",
        return_value=repo,
    ):
        summary = worker.dispatch_one(10)
    assert summary.claimed == 0
    assert adapter.submit_order_calls == 0


def test_worker_success_submit_exactly_once() -> None:
    adapter = CountingAdapter()
    entity = _entity()
    session = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = False
    factory = MagicMock(return_value=cm)
    repo = MagicMock()
    repo.get.return_value = entity
    idem = MagicMock()
    idem.begin.return_value = SimpleNamespace(
        status_code="PROCESSING", result_json=None
    )
    worker = OrderOutboxWorker(
        session_factory=factory,
        dispatcher=OrderOutboxDispatcher(adapter, session=session),
        worker_id="test-worker",
    )
    with (
        patch(
            "stock_platform.order.outbox_worker.OrderOutboxRepository",
            return_value=repo,
        ),
        patch(
            "stock_platform.order.outbox_worker.PostgreSqlIdempotencyRepository",
            return_value=idem,
        ),
        patch.object(
            OrderOutboxWorker,
            "_order_already_has_broker_id",
            return_value=False,
        ),
        patch.object(
            OrderOutboxWorker, "_assert_live_dispatch_allowed"
        ),
        patch(
            "stock_platform.order.outbox_dispatch_safety.assert_live_outbox_dispatch_safety"
        ),
        patch(
            "stock_platform.order.live_dry_run.should_block_live_dry_run",
            return_value=False,
        ),
        patch(
            "stock_platform.order.live_shadow.should_block_live_broker_call",
            return_value=False,
        ),
        patch(
            "stock_platform.order.outbox_dispatcher.resolve_outbox_adapter",
            return_value=adapter,
        ),
        patch.object(OrderOutboxWorker, "_finalize_smoke_one_shot_if_needed"),
        patch.object(OrderOutboxWorker, "_apply_order_broker_result"),
        patch.object(OrderOutboxWorker, "_maybe_mock_auto_fill"),
    ):
        summary = worker._run_claimed([(10, 1)])
    assert summary.succeeded == 1
    assert adapter.submit_order_calls == 1
    assert adapter.cancel_order_calls == 0
    assert adapter.amend_order_calls == 0
    repo.mark_done.assert_called()


def test_worker_idempotent_replay_does_not_resubmit() -> None:
    adapter = CountingAdapter()
    entity = _entity()
    session = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = False
    factory = MagicMock(return_value=cm)
    repo = MagicMock()
    repo.get.return_value = entity
    idem = MagicMock()
    idem.begin.return_value = SimpleNamespace(
        status_code="COMPLETED",
        result_json={"accepted": True, "broker_order_id": "x"},
    )
    worker = OrderOutboxWorker(
        session_factory=factory,
        dispatcher=OrderOutboxDispatcher(adapter),
        worker_id="test-worker",
    )
    with (
        patch(
            "stock_platform.order.outbox_worker.OrderOutboxRepository",
            return_value=repo,
        ),
        patch(
            "stock_platform.order.outbox_worker.PostgreSqlIdempotencyRepository",
            return_value=idem,
        ),
        patch.object(
            OrderOutboxWorker,
            "_order_already_has_broker_id",
            return_value=False,
        ),
        patch.object(
            OrderOutboxWorker, "_assert_live_dispatch_allowed"
        ),
        patch(
            "stock_platform.order.outbox_dispatch_safety.assert_live_outbox_dispatch_safety"
        ),
        patch(
            "stock_platform.order.live_dry_run.should_block_live_dry_run",
            return_value=False,
        ),
        patch(
            "stock_platform.order.live_shadow.should_block_live_broker_call",
            return_value=False,
        ),
        patch.object(OrderOutboxWorker, "_finalize_smoke_one_shot_if_needed"),
        patch.object(OrderOutboxWorker, "_apply_order_broker_result"),
        patch.object(OrderOutboxWorker, "_maybe_mock_auto_fill"),
    ):
        summary = worker._run_claimed([(10, 1)])
    assert summary.succeeded == 1
    assert adapter.submit_order_calls == 0


# ---------------------------------------------------------------------------
# UPBIT / KIWOOM regression
# ---------------------------------------------------------------------------


def test_upbit_blocked_and_success() -> None:
    session = MagicMock()
    adapter = CountingAdapter()
    uba = _uba(broker="UPBIT")
    patches, _ = _enter_live_pass(session, uba, kill_on=True)
    try:
        with pytest.raises(OutboxDispatchSafetyError):
            with patch(
                "stock_platform.order.outbox_dispatcher.resolve_outbox_adapter",
                return_value=adapter,
            ):
                OrderOutboxDispatcher(adapter, session=session).dispatch(
                    event_type="SUBMIT_ORDER",
                    payload=_payload(broker="UPBIT"),
                    idempotency_key="u-block",
                    session=session,
                    outbox_id=1,
                )
    finally:
        _exit_patches(patches)
    assert adapter.submit_order_calls == 0

    adapter2 = CountingAdapter()
    session2 = MagicMock()
    patches2, _ = _enter_live_pass(session2, _uba(broker="UPBIT"))
    try:
        with patch(
            "stock_platform.order.outbox_dispatcher.resolve_outbox_adapter",
            return_value=adapter2,
        ):
            OrderOutboxDispatcher(adapter2, session=session2).dispatch(
                event_type="SUBMIT_ORDER",
                payload=_payload(broker="UPBIT"),
                idempotency_key="u-ok",
                session=session2,
                outbox_id=2,
            )
    finally:
        _exit_patches(patches2)
    assert adapter2.submit_order_calls == 1


def test_kiwoom_success_and_kill_pause_recovery_zero() -> None:
    session = MagicMock()
    uba = _uba(uba_id=1381, broker="KIWOOM")
    payload = _payload(uba_id=1381, broker="KIWOOM")
    adapter = CountingAdapter()
    patches, _ = _enter_live_pass(session, uba)
    try:
        with patch(
            "stock_platform.order.outbox_dispatcher.resolve_outbox_adapter",
            return_value=adapter,
        ):
            OrderOutboxDispatcher(adapter, session=session).dispatch(
                event_type="SUBMIT_ORDER",
                payload=payload,
                idempotency_key="k-ok",
                session=session,
                outbox_id=3,
            )
    finally:
        _exit_patches(patches)
    assert adapter.submit_order_calls == 1

    for kwargs, code in (
        ({"kill_on": True}, REASON_KILL_SWITCH_ACTIVE),
        (
            {"recovery_error": ("trading_paused", "paused")},
            REASON_TRADING_PAUSED,
        ),
        (
            {"recovery_error": ("recovery_not_ready", "FAILED")},
            REASON_RECOVERY_NOT_READY,
        ),
    ):
        blocked = CountingAdapter()
        s = MagicMock()
        p, _ = _enter_live_pass(s, _uba(uba_id=1381, broker="KIWOOM"), **kwargs)
        try:
            with pytest.raises(OutboxDispatchSafetyError) as ei:
                with patch(
                    "stock_platform.order.outbox_dispatcher.resolve_outbox_adapter",
                    return_value=blocked,
                ):
                    OrderOutboxDispatcher(blocked, session=s).dispatch(
                        event_type="SUBMIT_ORDER",
                        payload=payload,
                        idempotency_key="k-block",
                        session=s,
                        outbox_id=4,
                    )
            assert ei.value.reason_code == code
        finally:
            _exit_patches(p)
        assert blocked.submit_order_calls == 0
        assert blocked.cancel_order_calls == 0
        assert blocked.amend_order_calls == 0


# ---------------------------------------------------------------------------
# Audit / secret safety
# ---------------------------------------------------------------------------


def test_audit_has_ids_without_secrets() -> None:
    session = MagicMock()
    payload = _payload()
    payload["access_key"] = "should-not-appear"
    payload["secret_key"] = "should-not-appear"
    payload["arm_token"] = "should-not-appear"
    with (
        patch(
            "stock_platform.order.outbox_dispatch_safety.emit_live_safety_audit"
        ) as live_audit,
        patch(
            "stock_platform.order.outbox_dispatch_safety.record_outbox_audit"
        ) as ob_audit,
    ):
        emit_outbox_dispatch_safety_rejection(
            session,
            reason_code=REASON_KILL_SWITCH_ACTIVE,
            payload=payload,
            outbox_id=99,
            worker_id="test-worker",
            trading_order_id=20,
        )
    detail = live_audit.call_args.kwargs["detail"]
    assert detail["outbox_id"] == 99
    assert detail["trading_order_id"] == 20
    assert detail["user_broker_account_id"] == 1380
    assert detail["broker"] == "UPBIT"
    assert detail["reason_code"] == REASON_KILL_SWITCH_ACTIVE
    assert "timestamp" in detail
    assert "access_key" not in detail
    assert "secret_key" not in detail
    assert "arm_token" not in detail
    ob = ob_audit.call_args.kwargs
    assert ob["event_type"] == AUDIT_EVENT_DISPATCH_SAFETY_REJECTED
    assert "access_key" not in ob["detail"]


def test_live_outbox_worker_auto_start_remains_false() -> None:
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    assert bool(getattr(settings, "live_outbox_worker_auto_start", False)) is False
