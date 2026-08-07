"""Broker-aware Live Trading Transition — UPBIT ACCOUNT / KIWOOM 회귀.

실제 adapter·Upbit /v1/orders·DB Activation 발급 없음 (mock only).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.live_transition_guard import (
    LiveTradingTransitionGuard,
)
from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)
from stock_platform.broker.live_transition_validators import (
    APPROVAL_PHRASE_BY_BROKER,
    UpbitLiveTransitionValidator,
)
from stock_platform.common.settings import get_settings
from stock_platform.order.outbox_worker import OrderOutboxWorker


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _kiwoom_ready_env(monkeypatch) -> None:
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_ACCOUNT_NUMBER", "123456")
    monkeypatch.setenv("KIWOOM_APP_KEY", "key")
    monkeypatch.setenv("KIWOOM_SECRET_KEY", "secret")
    monkeypatch.setenv("KIWOOM_ORDER_WS_SUBSCRIBE_JSON", "{}")
    monkeypatch.setenv("KIWOOM_RECOVERY_START_TRADING", "false")
    get_settings.cache_clear()


def _upbit_ready_env(monkeypatch) -> None:
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("UPBIT_USE_MOCK", "false")
    # KIWOOM 오염 — UPBIT validate에 영향 없어야 함
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    get_settings.cache_clear()


def _uba(
    *,
    uba_id: int = 1380,
    broker: str = "UPBIT",
    conn: str = "CONNECTED",
    active: bool = True,
):
    return SimpleNamespace(
        user_broker_account_id=uba_id,
        user_id=1,
        broker_code=broker,
        connection_status=conn,
        is_active=active,
        deleted_at=None,
        live_order_enabled=False,
        live_armed=False,
    )


def _patch_upbit_gates(
    *,
    cred_verified: bool = True,
    recovery_ok: bool = True,
    conflicts: int = 0,
    ks_off: bool = True,
    account_paused: bool = False,
    db_open: int = 0,
):
    class _Cred:
        def __init__(self, *_a, **_k):
            pass

        def status(self, *_a, **_k):
            return SimpleNamespace(
                is_active=cred_verified,
                connected=cred_verified,
                verification_status="VERIFIED" if cred_verified else "PENDING",
            )

    def _recovery(session, uba_id, *, raise_error):
        if not recovery_ok:
            raise raise_error("recovery_not_ready", "FAILED")
        return {"trading_paused": False, "recovery_status": "SUCCESS"}

    def _risk(session, uba, *, raise_error):
        if account_paused:
            raise raise_error("account_paused", "paused")
        return {"account_paused": False}

    class _Conflict:
        def __init__(self, *_a, **_k):
            pass

        def count_active_for_uba(self, *_a, **_k):
            return conflicts

        def count_blocking_orders_for_uba(self, *_a, **_k):
            return {
                "db_open": db_open,
                "submission_unknown": 0,
                "cancel_pending": 0,
                "replace_pending": 0,
            }

    class _KS:
        GLOBAL_SCOPE = "GLOBAL"

        def __init__(self, *_a, **_k):
            pass

        def is_active_for_scopes(self, *_a, **_k):
            return not ks_off

    return (
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService",
            _Cred,
        ),
        patch(
            "stock_platform.trading.runtime_control_gates.assert_recovery_ready",
            side_effect=_recovery,
        ),
        patch(
            "stock_platform.trading.runtime_control_gates.assert_risk_account_not_paused",
            side_effect=_risk,
        ),
        patch(
            "stock_platform.broker.recovery_conflict_service.BrokerRecoveryConflictService",
            _Conflict,
        ),
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService",
            _KS,
        ),
    )


def _upbit_validate(
    monkeypatch,
    session: MagicMock,
    uba: Any,
    **gate_kw: Any,
):
    _upbit_ready_env(monkeypatch)
    session.get.return_value = uba
    patches = _patch_upbit_gates(**gate_kw)
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        return LiveTradingTransitionService(session).validate(
            max_order_amount=Decimal("10000"),
            max_daily_loss=Decimal("50000"),
            paper_validation_approved=True,
            scope="ACCOUNT",
            broker_code="UPBIT",
            user_broker_account_id=int(uba.user_broker_account_id),
        )


def test_a_upbit_uba_ready(monkeypatch) -> None:
    plan = _upbit_validate(monkeypatch, MagicMock(), _uba())
    assert plan.ready is True
    assert plan.broker_code == "UPBIT"
    assert plan.scope == "ACCOUNT"
    assert plan.user_broker_account_id == 1380


def test_b_kiwoom_mock_true_ignored_for_upbit(monkeypatch) -> None:
    plan = _upbit_validate(monkeypatch, MagicMock(), _uba())
    assert plan.ready is True
    assert get_settings().kiwoom_use_mock is True


def test_c_kiwoom_live_false_ignored_for_upbit(monkeypatch) -> None:
    plan = _upbit_validate(monkeypatch, MagicMock(), _uba())
    assert plan.ready is True
    assert get_settings().kiwoom_live_order_enabled is False


def test_d_upbit_use_mock_blocks(monkeypatch) -> None:
    _upbit_ready_env(monkeypatch)
    monkeypatch.setenv("UPBIT_USE_MOCK", "true")
    get_settings.cache_clear()
    session = MagicMock()
    session.get.return_value = _uba()
    patches = _patch_upbit_gates()
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        plan = LiveTradingTransitionService(session).validate(
            max_order_amount=Decimal("10000"),
            max_daily_loss=Decimal("50000"),
            paper_validation_approved=True,
            scope="ACCOUNT",
            user_broker_account_id=1380,
        )
    assert plan.ready is False
    assert any(
        c.code.value == "MOCK_MODE_DISABLED" and c.status.value == "FAIL"
        for c in plan.checks
    )


def test_e_upbit_live_disabled_blocks(monkeypatch) -> None:
    _upbit_ready_env(monkeypatch)
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    get_settings.cache_clear()
    session = MagicMock()
    session.get.return_value = _uba()
    patches = _patch_upbit_gates()
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        plan = LiveTradingTransitionService(session).validate(
            max_order_amount=Decimal("10000"),
            max_daily_loss=Decimal("50000"),
            paper_validation_approved=True,
            scope="ACCOUNT",
            user_broker_account_id=1380,
        )
    assert plan.ready is False


def test_f_global_live_disabled_blocks(monkeypatch) -> None:
    _upbit_ready_env(monkeypatch)
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "false")
    get_settings.cache_clear()
    session = MagicMock()
    session.get.return_value = _uba()
    patches = _patch_upbit_gates()
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        plan = LiveTradingTransitionService(session).validate(
            max_order_amount=Decimal("10000"),
            max_daily_loss=Decimal("50000"),
            paper_validation_approved=True,
            scope="ACCOUNT",
            user_broker_account_id=1380,
        )
    assert plan.ready is False


def test_g_credential_unverified_blocks(monkeypatch) -> None:
    plan = _upbit_validate(
        monkeypatch, MagicMock(), _uba(), cred_verified=False
    )
    assert plan.ready is False


def test_h_connection_not_connected_blocks(monkeypatch) -> None:
    plan = _upbit_validate(
        monkeypatch, MagicMock(), _uba(conn="DISCONNECTED")
    )
    assert plan.ready is False


def test_i_recovery_conflict_paused_ks_blocks(monkeypatch) -> None:
    assert (
        _upbit_validate(
            monkeypatch, MagicMock(), _uba(), recovery_ok=False
        ).ready
        is False
    )
    assert (
        _upbit_validate(
            monkeypatch, MagicMock(), _uba(), conflicts=1
        ).ready
        is False
    )
    assert (
        _upbit_validate(
            monkeypatch, MagicMock(), _uba(), ks_off=False
        ).ready
        is False
    )
    assert (
        _upbit_validate(
            monkeypatch, MagicMock(), _uba(), account_paused=True
        ).ready
        is False
    )
    assert (
        _upbit_validate(
            monkeypatch, MagicMock(), _uba(), db_open=1
        ).ready
        is False
    )


def test_j_uba1380_activation_rejects_other_uba_dispatch() -> None:
    entity = SimpleNamespace(
        broker_code="UPBIT",
        scope="ACCOUNT",
        user_broker_account_id=1380,
        enabled=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert (
        LiveTradingTransitionService.transition_matches_dispatch(
            entity,  # type: ignore[arg-type]
            broker_code="UPBIT",
            user_broker_account_id=9999,
        )
        is False
    )
    assert (
        LiveTradingTransitionService.transition_matches_dispatch(
            entity,  # type: ignore[arg-type]
            broker_code="UPBIT",
            user_broker_account_id=1380,
        )
        is True
    )


def test_k_kiwoom_validation_regression(monkeypatch) -> None:
    _kiwoom_ready_env(monkeypatch)
    service = LiveTradingTransitionService.__new__(LiveTradingTransitionService)
    service._session = MagicMock()
    plan = service.validate(
        max_order_amount=Decimal("10000"),
        max_daily_loss=Decimal("50000"),
        paper_validation_approved=True,
    )
    assert plan.ready is True
    assert plan.broker_code == "KIWOOM"


def test_l_expired_activation_require_active_rejects() -> None:
    session = MagicMock()
    expired = SimpleNamespace(
        enabled=True,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        broker_code="UPBIT",
        scope="ACCOUNT",
        user_broker_account_id=1380,
        activation_status="ACTIVE",
        disabled_at=None,
        disable_reason=None,
    )
    session.scalars.return_value = [expired]
    with pytest.raises(PermissionError, match="No active live trading"):
        LiveTradingTransitionGuard(session).require_active(
            broker_code="UPBIT",
            user_broker_account_id=1380,
        )
    assert expired.enabled is False
    assert expired.activation_status == "EXPIRED"


def test_m_wrong_broker_activation_rejects() -> None:
    entity = SimpleNamespace(
        broker_code="KIWOOM",
        scope="BROKER",
        user_broker_account_id=None,
    )
    assert (
        LiveTradingTransitionService.transition_matches_dispatch(
            entity,  # type: ignore[arg-type]
            broker_code="UPBIT",
            user_broker_account_id=1380,
        )
        is False
    )


def test_n_one_shot_still_requires_matching_activation(monkeypatch) -> None:
    """grant가 있어도 Activation 불일치면 Worker gate 거절."""

    session = MagicMock()
    uba = _uba()
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch.object(
            LiveTradingTransitionGuard,
            "require_active",
            side_effect=PermissionError(
                "No active live trading transition approval"
            ),
        ),
    ):
        with pytest.raises(PermissionError, match="No active live trading"):
            OrderOutboxWorker._assert_live_dispatch_allowed(
                session,
                {
                    "environment": "LIVE",
                    "user_broker_account_id": 1380,
                    "broker_code": "UPBIT",
                    "owner_user_id": 1,
                    "order_id": 1,
                },
                outbox_id=1117,
            )


def test_o_worker_gate_pass_without_adapter_call(monkeypatch) -> None:
    create_calls: list[Any] = []

    class FakeAdapter:
        def create_order(self, *a, **k):
            create_calls.append(1)
            raise AssertionError("adapter must not be called")

    session = MagicMock()
    uba = _uba()
    uba.live_order_enabled = True
    uba.live_armed = True
    session.get.return_value = uba
    active = SimpleNamespace(
        broker_code="UPBIT",
        scope="ACCOUNT",
        user_broker_account_id=1380,
        enabled=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch.object(
            LiveTradingTransitionService,
            "get_active",
            return_value=active,
        ),
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService"
        ) as ARM,
    ):
        ARM.return_value.expire_if_needed.return_value = False
        OrderOutboxWorker._assert_live_dispatch_allowed(
            session,
            {
                "environment": "LIVE",
                "user_broker_account_id": 1380,
                "broker_code": "UPBIT",
                "owner_user_id": 1,
                "order_id": 1,
            },
            outbox_id=1117,
        )
        _ = FakeAdapter  # spy only
    assert create_calls == []


def test_approval_phrase_broker_split() -> None:
    assert APPROVAL_PHRASE_BY_BROKER["KIWOOM"] == "ENABLE KIWOOM LIVE TRADING"
    assert APPROVAL_PHRASE_BY_BROKER["UPBIT"] == "ENABLE UPBIT LIVE TRADING"
    assert (
        LiveTradingTransitionService.REQUIRED_APPROVAL_PHRASE
        == "ENABLE KIWOOM LIVE TRADING"
    )


def test_upbit_broker_scope_without_uba_rejected(monkeypatch) -> None:
    _upbit_ready_env(monkeypatch)
    session = MagicMock()
    plan = LiveTradingTransitionService(session).validate(
        max_order_amount=Decimal("10000"),
        max_daily_loss=Decimal("50000"),
        paper_validation_approved=True,
        scope="BROKER",
        broker_code="UPBIT",
    )
    assert plan.ready is False


def test_client_broker_mismatch_uba_fail_closed(monkeypatch) -> None:
    _upbit_ready_env(monkeypatch)
    session = MagicMock()
    session.get.return_value = _uba(broker="UPBIT")
    plan = LiveTradingTransitionService(session).validate(
        max_order_amount=Decimal("10000"),
        max_daily_loss=Decimal("50000"),
        paper_validation_approved=True,
        scope="ACCOUNT",
        broker_code="KIWOOM",
        user_broker_account_id=1380,
    )
    assert plan.ready is False
