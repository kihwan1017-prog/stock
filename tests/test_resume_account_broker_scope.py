"""Resume API — UBA broker_code SoT (KIWOOM + UPBIT). broker network 없음."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
)
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
    RecoveryConflictError,
)

_EMPTY_BLOCKING = {
    "db_open": 0,
    "submission_unknown": 0,
    "cancel_pending": 0,
    "replace_pending": 0,
}


def _uba(*, broker: str = "KIWOOM", **extra: object) -> SimpleNamespace:
    base = {
        "is_active": True,
        "broker_code": broker,
        "connection_status": "CONNECTED",
        "live_order_enabled": False,
        "live_armed": False,
    }
    base.update(extra)
    return SimpleNamespace(**base)


def _state(*, broker: str = "KIWOOM", paused: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        broker_code=broker,
        trading_paused=paused,
        recovery_status="SUCCESS",
        last_error_summary=None,
        last_error_code=None,
        auto_retry_enabled=True,
        updated_at=None,
    )


def _svc(
    session: MagicMock,
    *,
    uba: SimpleNamespace,
    state: SimpleNamespace | None,
    conflicts: int = 0,
    blocking: dict | None = None,
):
    """count/vault를 production 계약에 맞게 stub — resume_check 미연결."""

    session.get.return_value = uba
    captured: dict = {}

    def _scalar(stmt, *args, **kwargs):
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        captured["state_sql"] = sql
        return state

    session.scalar.side_effect = _scalar
    svc = BrokerRecoveryConflictService(session)
    svc.count_active_for_uba = MagicMock(return_value=conflicts)
    svc.count_blocking_orders_for_uba = MagicMock(
        return_value=dict(blocking or _EMPTY_BLOCKING)
    )
    return svc, captured


def _resume(svc, uba_id: int = 1381, *, kill: bool = False):
    return svc.resume_account(
        uba_id,
        actor="admin:7",
        reason="OPERATOR_RESUME_KIWOOM_1381",
        correlation_id="corr-1381",
        kill_switch_active=kill,
    )


def test_a_kiwoom_healthy_paused_resumes() -> None:
    session = MagicMock()
    uba = _uba(broker="KIWOOM")
    state = _state(broker="KIWOOM", paused=True)
    svc, captured = _svc(session, uba=uba, state=state)
    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ) as assert_live:
        result = _resume(svc)
    assert result["resumed"] is True
    assert result["broker_code"] == "KIWOOM"
    assert state.trading_paused is False
    assert state.recovery_status == "SUCCESS"
    assert state.last_error_code is None
    assert assert_live.call_args.kwargs["broker_code"] == "KIWOOM"
    assert "KIWOOM" in captured["state_sql"]
    assert "UPBIT" not in captured["state_sql"]
    assert result["live_arm_unchanged"] is True
    assert result["scheduler_unchanged"] is True
    session.flush.assert_called()


def test_b_kiwoom_credential_mismatch_fails() -> None:
    session = MagicMock()
    svc, _ = _svc(session, uba=_uba(), state=_state())
    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        side_effect=BrokerCredentialVaultError(
            "credential_broker_mismatch", "mismatch"
        ),
    ):
        with pytest.raises(RecoveryConflictError) as exc:
            _resume(svc)
    assert exc.value.code == "credential_broker_mismatch"
    session.flush.assert_not_called()


def test_c_kiwoom_conflict_fails() -> None:
    session = MagicMock()
    svc, _ = _svc(session, uba=_uba(), state=_state(), conflicts=1)
    with pytest.raises(RecoveryConflictError) as exc:
        _resume(svc)
    assert exc.value.code == "unresolved_conflicts"


def test_d_kiwoom_blocking_order_fails() -> None:
    session = MagicMock()
    blocking = dict(_EMPTY_BLOCKING)
    blocking["db_open"] = 2
    svc, _ = _svc(session, uba=_uba(), state=_state(), blocking=blocking)
    with pytest.raises(RecoveryConflictError) as exc:
        _resume(svc)
    assert exc.value.code == "db_open_orders"


def test_e_kiwoom_kill_fails() -> None:
    session = MagicMock()
    svc, _ = _svc(session, uba=_uba(), state=_state())
    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ):
        with pytest.raises(RecoveryConflictError) as exc:
            _resume(svc, kill=True)
    assert exc.value.code == "kill_switch_active"


def test_f_kiwoom_running_fails() -> None:
    session = MagicMock()
    state = _state()
    state.recovery_status = "RUNNING"
    svc, _ = _svc(session, uba=_uba(), state=state)
    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ):
        with pytest.raises(RecoveryConflictError) as exc:
            _resume(svc)
    assert exc.value.code == "recovery_running"
    assert state.trading_paused is True


def test_g_kiwoom_already_resumed_idempotent() -> None:
    session = MagicMock()
    state = _state(paused=False)
    svc, _ = _svc(session, uba=_uba(), state=state)
    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ):
        first = _resume(svc)
        second = _resume(svc)
    assert first["already_resumed"] is True
    assert first["resumed"] is False
    assert second["already_resumed"] is True
    assert state.trading_paused is False
    session.flush.assert_not_called()


def test_h_i_kiwoom_state_broker_scoped_not_upbit() -> None:
    session = MagicMock()
    svc, captured = _svc(
        session, uba=_uba(broker="KIWOOM"), state=_state(broker="KIWOOM")
    )
    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ):
        _resume(svc)
    sql = captured["state_sql"]
    assert "KIWOOM" in sql
    assert "UPBIT" not in sql


def test_j_upbit_resume_regression() -> None:
    session = MagicMock()
    uba = _uba(broker="UPBIT")
    state = _state(broker="UPBIT", paused=True)
    svc, captured = _svc(session, uba=uba, state=state)
    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ) as assert_live:
        result = _resume(svc, 58)
    assert result["resumed"] is True
    assert result["broker_code"] == "UPBIT"
    assert assert_live.call_args.kwargs["broker_code"] == "UPBIT"
    assert "UPBIT" in captured["state_sql"]
    assert state.trading_paused is False


def test_k_unsupported_broker_fail_closed() -> None:
    session = MagicMock()
    svc, _ = _svc(
        session, uba=_uba(broker="PAPER"), state=_state(broker="PAPER")
    )
    with pytest.raises(RecoveryConflictError) as exc:
        _resume(svc)
    assert exc.value.code == "unsupported_broker"
    session.flush.assert_not_called()


def test_l_cross_account_isolation() -> None:
    session = MagicMock()
    other = _state(broker="KIWOOM", paused=True)
    target = _state(broker="KIWOOM", paused=True)
    svc, _ = _svc(session, uba=_uba(), state=target)
    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ):
        _resume(svc, 1381)
    assert target.trading_paused is False
    assert other.trading_paused is True


def test_m_n_o_live_arm_scheduler_unchanged() -> None:
    session = MagicMock()
    uba = _uba(live_order_enabled=False, live_armed=False)
    state = _state(paused=True)
    svc, _ = _svc(session, uba=uba, state=state)
    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ):
        result = _resume(svc)
    assert uba.live_order_enabled is False
    assert uba.live_armed is False
    assert result["live_order_enabled"] is False
    assert result["live_armed"] is False
    assert result["live_arm_unchanged"] is True
    assert result["scheduler_unchanged"] is True


def test_p_q_r_no_order_or_network_side_effects() -> None:
    session = MagicMock()
    svc, _ = _svc(session, uba=_uba(), state=_state())
    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ):
        _resume(svc)
    assert not any(
        "UpbitOrderRestClient" in str(c) for c in session.mock_calls
    )


def test_source_has_no_resume_account_upbit_hardcode() -> None:
    from pathlib import Path

    text = Path(
        "src/stock_platform/broker/recovery_conflict_service.py"
    ).read_text(encoding="utf-8")
    start = text.index("def resume_account(")
    end = text.index("def _vault_order_client(")
    body = text[start:end]
    assert 'broker_code="UPBIT"' not in body
    assert 'broker_code == "UPBIT"' not in body
    assert "broker_code=broker" in body
    assert "resume_check" not in body
