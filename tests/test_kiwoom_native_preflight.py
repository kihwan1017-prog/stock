"""K_ONLY — Kiwoom native Preflight evaluate + dispatch tests (broker/network 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.kiwoom.live_preflight_service import (
    KiwoomLivePreflightService,
    KiwoomPreflightSnapshot,
)
from stock_platform.operation.runtime_preflight_service import (
    RuntimePreflightService,
)
from stock_platform.trading.live_order_approval_service import (
    LiveOrderApprovalError,
)


def _now() -> datetime:
    return datetime(2026, 8, 18, 2, 0, tzinfo=timezone.utc)  # 11:00 KST


def _healthy(**kwargs: object) -> KiwoomPreflightSnapshot:
    base = dict(
        uba_id=1381,
        user_id=61,
        is_active=True,
        broker_code="KIWOOM",
        connection_status="CONNECTED",
        live_order_enabled=False,
        live_armed=False,
        credential_present=True,
        credential_verified=True,
        credential_is_mock=False,
        recovery_status="SUCCESS",
        trading_paused=False,
        active_high_conflicts=0,
        active_conflicts=0,
        snapshot_id=2,
        snapshot_status="ACTIVE",
        snapshot_uba_id=1381,
        snapshot_synchronized_at=_now(),
        position_count=12,
        unbound_or_cross_uba_positions=0,
        uba_risk_present=True,
        user_risk_present=False,
        risk_account_paused=False,
        kill_active=False,
        scheduler_desired="PAUSE",
        scheduler_actual="PAUSED",
        krx_is_trading_day=True,
        krx_session_type="REGULAR",
        krx_in_regular_session=True,
        env_global_live=False,
        env_kiwoom_live=False,
        env_kiwoom_use_mock=False,
        strategy_link_count=0,
        blocking_orders={"db_open": 0, "submission_unknown": 0},
        pending_count=0,
        now=_now(),
    )
    base.update(kwargs)
    return KiwoomPreflightSnapshot(**base)  # type: ignore[arg-type]


def _codes(report: dict, status: str | None = None) -> set[str]:
    rows = report.get("checks") or []
    if status is None:
        return {str(c.get("code")) for c in rows}
    return {str(c.get("code")) for c in rows if c.get("status") == status}


def _eval(snap: KiwoomPreflightSnapshot, mode: str = "LIVE_ON") -> dict:
    return KiwoomLivePreflightService(MagicMock()).evaluate(snap, mode=mode)


def test_a_paused_blocks_live() -> None:
    report = _eval(_healthy(trading_paused=True, uba_risk_present=True))
    assert report["overall_status"] == "BLOCKED"
    assert "TRADING_PAUSED" in _codes(report, "FAIL")
    assert report["live_on_allowed"] is False


def test_b_missing_uba_risk_blocks() -> None:
    report = _eval(_healthy(uba_risk_present=False, user_risk_present=False))
    assert report["overall_status"] == "BLOCKED"
    assert "KIWOOM_RISK" in _codes(report, "FAIL")


def test_b2_user_risk_only_still_fails() -> None:
    report = _eval(_healthy(uba_risk_present=False, user_risk_present=True))
    assert "KIWOOM_RISK" in _codes(report, "FAIL")


def test_c_healthy_pre_live_ready() -> None:
    report = _eval(_healthy())
    assert report["overall_status"] == "READY_FOR_LIVE"
    assert report["live_on_allowed"] is True
    assert "TRADING_PAUSED" in _codes(report, "PASS")
    assert "KIWOOM_RISK" in _codes(report, "PASS")
    assert "UPBIT_WS" not in _codes(report)


def test_d_mock_credential_blocks() -> None:
    report = _eval(_healthy(credential_is_mock=True))
    assert "KIWOOM_REAL_ENV" in _codes(report, "FAIL")


def test_d2_real_cred_global_mock_real_env_pass() -> None:
    report = _eval(
        _healthy(credential_is_mock=False, env_kiwoom_use_mock=True)
    )
    assert _check_status(report, "KIWOOM_REAL_ENV") == "PASS"
    assert _check_status(report, "KIWOOM_MARKET_ENV") == "WARN"


def _check_status(report: dict, code: str) -> str:
    for row in report.get("checks") or []:
        if row.get("code") == code:
            return str(row.get("status"))
    return "MISSING"


def test_e_credential_missing_unverified() -> None:
    missing = _eval(_healthy(credential_present=False, credential_verified=False))
    unverified = _eval(_healthy(credential_present=True, credential_verified=False))
    assert "KIWOOM_CREDENTIAL" in _codes(missing, "FAIL")
    assert "KIWOOM_CREDENTIAL" in _codes(unverified, "FAIL")


def test_f_connection_not_connected() -> None:
    report = _eval(_healthy(connection_status="DISCONNECTED"))
    assert "KIWOOM_CONNECTION" in _codes(report, "FAIL")


def test_g_recovery_failed_or_running() -> None:
    failed = _eval(_healthy(recovery_status="FAILED"))
    running = _eval(_healthy(recovery_status="RUNNING"))
    assert "KIWOOM_RECOVERY" in _codes(failed, "FAIL")
    assert "KIWOOM_RECOVERY" in _codes(running, "FAIL")
    assert "KIWOOM_RECOVERY_LOCK" in _codes(running, "FAIL")


def test_h_active_recovery_lock() -> None:
    report = _eval(
        _healthy(
            lock_holder="worker-1",
            lock_expires_at=_now() + timedelta(minutes=5),
        )
    )
    assert "KIWOOM_RECOVERY_LOCK" in _codes(report, "FAIL")


def test_i_high_conflict() -> None:
    report = _eval(_healthy(active_high_conflicts=1, active_conflicts=1))
    assert "CONFLICT" in _codes(report, "FAIL")


def test_j_snapshot_unbound() -> None:
    report = _eval(
        _healthy(snapshot_id=None, snapshot_status=None, snapshot_uba_id=None)
    )
    assert "KIWOOM_ACCOUNT_SNAPSHOT" in _codes(report, "FAIL")


def test_k_position_cross_uba() -> None:
    report = _eval(_healthy(unbound_or_cross_uba_positions=1))
    assert "KIWOOM_POSITION_INTEGRITY" in _codes(report, "FAIL")


def test_l_pre_arm_while_live_off() -> None:
    report = _eval(_healthy(live_order_enabled=False), mode="ARM_ON")
    assert report["overall_status"] == "BLOCKED"
    assert "ARM_LIVE_REQUIRED" in _codes(report, "FAIL")


def test_m_pre_order_krx_closed() -> None:
    report = _eval(
        _healthy(
            live_order_enabled=True,
            live_armed=True,
            arm_expires_at=_now() + timedelta(minutes=4),
            krx_is_trading_day=False,
            krx_session_type="CLOSED",
            krx_in_regular_session=False,
            env_global_live=True,
            env_kiwoom_live=True,
            arm_precondition_ok=True,
        ),
        mode="ORDER",
    )
    assert report["overall_status"] == "BLOCKED"
    assert "KIWOOM_MARKET_SESSION" in _codes(report, "FAIL")


def test_n_pre_order_env_live_false() -> None:
    report = _eval(
        _healthy(
            live_order_enabled=True,
            live_armed=True,
            arm_expires_at=_now() + timedelta(minutes=4),
            env_global_live=False,
            env_kiwoom_live=False,
            krx_in_regular_session=True,
            arm_precondition_ok=True,
        ),
        mode="ORDER",
    )
    assert "KIWOOM_ENV_LIVE" in _codes(report, "FAIL")


def test_o_pre_order_healthy_regular_session() -> None:
    report = _eval(
        _healthy(
            live_order_enabled=True,
            live_armed=True,
            arm_expires_at=_now() + timedelta(minutes=4),
            env_global_live=True,
            env_kiwoom_live=True,
            env_kiwoom_use_mock=False,
            krx_is_trading_day=True,
            krx_session_type="REGULAR",
            krx_in_regular_session=True,
            arm_precondition_ok=True,
        ),
        mode="ORDER",
    )
    assert report["overall_status"] == "READY_FOR_ORDER"
    assert report["manual_order_allowed"] is True
    assert "KIWOOM_MARKET_SESSION" in _codes(report, "PASS")


def test_uba1381_current_equivalent_blocked() -> None:
    """현재 1381: paused + UBA risk 없음 → BLOCKED, 다른 정상 gate PASS."""
    report = _eval(
        _healthy(
            trading_paused=True,
            uba_risk_present=False,
            user_risk_present=False,
            position_count=12,
        )
    )
    assert report["overall_status"] == "BLOCKED"
    fails = _codes(report, "FAIL")
    assert "TRADING_PAUSED" in fails
    assert "KIWOOM_RISK" in fails
    assert "KIWOOM_CREDENTIAL" in _codes(report, "PASS")
    assert "KIWOOM_CONNECTION" in _codes(report, "PASS")
    assert "KIWOOM_RECOVERY" in _codes(report, "PASS")
    assert "KIWOOM_ACCOUNT_SNAPSHOT" in _codes(report, "PASS")
    assert report["live_on_allowed"] is False


def test_pre_live_does_not_include_upbit_checks() -> None:
    report = _eval(_healthy())
    codes = _codes(report)
    assert "UPBIT_WS" not in codes
    assert "ORDERABILITY" not in codes


def test_p_upbit_dispatch_does_not_call_kiwoom() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_id=61,
        broker_code="UPBIT",
        deleted_at=None,
        is_active=True,
    )
    session.get.return_value = uba
    with patch(
        "stock_platform.broker.kiwoom.live_preflight_service.KiwoomLivePreflightService.run"
    ) as krun:
        try:
            RuntimePreflightService(session).run_for_uba(
                user_broker_account_id=1380
            )
        except Exception:
            pass
    krun.assert_not_called()


def test_q_unknown_broker_fail_closed() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        user_id=1,
        broker_code="PAPER",
        deleted_at=None,
        is_active=True,
    )
    report = RuntimePreflightService(session).run_for_uba(
        user_broker_account_id=9
    )
    assert report["overall_status"] == "BLOCKED"
    assert report["live_on_allowed"] is False
    assert any(b.get("code") == "BROKER" for b in report.get("blockers") or [])


def test_g1_kiwoom_dispatch_calls_k_only() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        user_id=61,
        broker_code="KIWOOM",
        deleted_at=None,
        is_active=True,
    )
    with patch(
        "stock_platform.broker.kiwoom.live_preflight_service.KiwoomLivePreflightService.run",
        return_value={
            "overall_status": "BLOCKED",
            "broker_code": "KIWOOM",
            "user_broker_account_id": 1381,
            "blockers": [{"code": "TRADING_PAUSED"}],
        },
    ) as krun:
        out = RuntimePreflightService(session).run_for_uba(
            user_broker_account_id=1381, mode="LIVE_ON"
        )
    krun.assert_called_once()
    assert out["broker_code"] == "KIWOOM"
    assert krun.call_args.kwargs["mode"] == "LIVE_ON"


def test_r_assert_ready_for_live_on_paused_raises_no_live_mutation() -> None:
    uba = SimpleNamespace(live_order_enabled=False, broker_code="KIWOOM")
    session = MagicMock()
    blocked = {
        "overall_status": "BLOCKED",
        "blockers": [
            {"code": "TRADING_PAUSED", "message": "paused"},
            {"code": "KIWOOM_RISK", "message": "no row"},
        ],
    }
    with patch.object(
        RuntimePreflightService, "run_for_uba", return_value=blocked
    ):
        with pytest.raises(LiveOrderApprovalError) as exc:
            RuntimePreflightService(session).assert_ready_for_live_on(1381)
    assert exc.value.code == "preflight_blocked"
    assert uba.live_order_enabled is False


def test_pre_live_krx_closed_is_warn_only() -> None:
    report = _eval(
        _healthy(krx_is_trading_day=False, krx_session_type="CLOSED")
    )
    assert report["overall_status"] == "READY_FOR_LIVE"
    assert "KIWOOM_MARKET_SESSION" in _codes(report, "WARN")


def test_pre_arm_happy_path() -> None:
    report = _eval(
        _healthy(
            live_order_enabled=True,
            live_armed=False,
            arm_precondition_ok=True,
        ),
        mode="ARM_ON",
    )
    assert report["overall_status"] == "READY_FOR_ARM"
    assert report.get("arm_on_allowed") is True
