"""KIWOOM execution vs market-data SoT alignment — targeted tests.

실 broker API / Activation / LIVE / ARM / Worker / Runner START 금지.
src 운영 패치 전에도 기존 Option D 계약은 PASS.
UBA-scoped evaluate_live_flag_consistency 는 패치 적용 전 skip.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.credential_adapter_factory import (
    build_kiwoom_order_config_from_vault,
)
from stock_platform.broker.credential_vault_service import ResolvedBrokerCredential
from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.kiwoom.execution_env import (
    KIWOOM_MOCK_EXECUTION_BASE,
    KIWOOM_REAL_EXECUTION_BASE,
    kiwoom_execution_base_url,
    kiwoom_global_mock_blocks_live_execution,
    kiwoom_market_env_is_mock,
    kiwoom_uba_has_explicit_real_execution,
)
from stock_platform.broker.live_config_gate import (
    assert_kiwoom_live_env_allows_orders,
    evaluate_live_flag_consistency,
)
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.common.settings import get_settings
from stock_platform.realtime.execution_scope import runner_scope_key
from stock_platform.realtime.kiwoom_runtime_run_gates import (
    evaluate_kiwoom_runtime_run_gates,
)


def _option_d_env(monkeypatch) -> None:
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("UPBIT_USE_MOCK", "false")
    get_settings.cache_clear()


def _uba_kwargs_supported() -> bool:
    sig = inspect.signature(evaluate_live_flag_consistency)
    return "user_broker_account_id" in sig.parameters


@pytest.fixture(autouse=True)
def _clear_settings() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- 1 explicit REAL + global market mock ---


def test_1_explicit_real_not_blocked_by_global_market_mock(monkeypatch) -> None:
    _option_d_env(monkeypatch)
    session = MagicMock()
    with patch(
        "stock_platform.broker.kiwoom.execution_env.kiwoom_uba_has_explicit_real_execution",
        return_value=True,
    ):
        assert (
            kiwoom_global_mock_blocks_live_execution(
                session, user_broker_account_id=1381
            )
            is False
        )
    assert kiwoom_market_env_is_mock() is True


def test_1_unscoped_flag_consistency_still_live_mock_conflict(monkeypatch) -> None:
    """패치 전 갭: UBA 없이 KIWOOM 플래그만 보면 CRITICAL conflict."""

    _option_d_env(monkeypatch)
    result = evaluate_live_flag_consistency(broker_code="KIWOOM")
    assert result.code == "LIVE_MOCK_CONFLICT"
    assert result.allowed is False
    assert result.status == "CRITICAL"


@pytest.mark.skipif(
    not _uba_kwargs_supported(),
    reason="PATCH_REQUIRED: evaluate_live_flag_consistency UBA kwargs (maintenance window)",
)
def test_1_uba_scoped_explicit_real_is_not_critical(monkeypatch) -> None:
    _option_d_env(monkeypatch)
    session = MagicMock()
    with patch(
        "stock_platform.broker.kiwoom.execution_env.kiwoom_global_mock_blocks_live_execution",
        return_value=False,
    ):
        result = evaluate_live_flag_consistency(
            broker_code="KIWOOM",
            session=session,
            user_broker_account_id=1381,
        )
    assert result.allowed is True
    assert result.code == "KIWOOM_EXPLICIT_REAL_EXECUTION"
    assert result.status in {"HEALTHY", "DEGRADED"}
    assert result.detail.get("execution_env") == "REAL"
    assert result.detail.get("market_env") == "MOCK"


# --- 2 mock credential BLOCK ---


def test_2_mock_credential_blocks_live_execution(monkeypatch) -> None:
    _option_d_env(monkeypatch)
    session = MagicMock()
    with patch(
        "stock_platform.broker.kiwoom.execution_env.kiwoom_uba_has_explicit_real_execution",
        return_value=False,
    ), patch(
        "stock_platform.broker.kiwoom.execution_env.kiwoom_uba_execution_is_mock",
        return_value=(True, True),
    ):
        assert (
            kiwoom_global_mock_blocks_live_execution(
                session, user_broker_account_id=1381
            )
            is True
        )


# --- 3 GLOBAL=false BLOCK ---


def test_3_global_live_false_blocks_kiwoom_orders(monkeypatch) -> None:
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    get_settings.cache_clear()
    result = evaluate_live_flag_consistency(broker_code="KIWOOM")
    assert result.allowed is False
    assert result.code == "LIVE_FLAG_MISMATCH_KIWOOM"
    with pytest.raises(PermissionError):
        assert_kiwoom_live_env_allows_orders()


# --- 4 KIWOOM_LIVE=false BLOCK ---


def test_4_kiwoom_live_false_blocks_orders(monkeypatch) -> None:
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    get_settings.cache_clear()
    result = evaluate_live_flag_consistency(broker_code="KIWOOM")
    assert result.code == "KIWOOM_LIVE_OFF"
    with pytest.raises(PermissionError, match="KIWOOM_LIVE_ORDER_ENABLED"):
        assert_kiwoom_live_env_allows_orders()


# --- 5 credential unverified BLOCK ---


def test_5_unverified_credential_blocks(monkeypatch) -> None:
    _option_d_env(monkeypatch)
    session = MagicMock()
    with patch(
        "stock_platform.broker.kiwoom.execution_env.kiwoom_uba_has_explicit_real_execution",
        return_value=False,
    ), patch(
        "stock_platform.broker.kiwoom.execution_env.kiwoom_uba_execution_is_mock",
        return_value=(None, False),
    ):
        assert (
            kiwoom_global_mock_blocks_live_execution(
                session, user_broker_account_id=1381
            )
            is True
        )


# --- 6 Activation validator Option D ---


def test_6_activation_validator_account_explicit_real_source() -> None:
    src = inspect.getsource(
        __import__(
            "stock_platform.broker.live_transition_validators",
            fromlist=["KiwoomLiveTransitionValidator"],
        ).KiwoomLiveTransitionValidator.validate
    )
    assert "ACCOUNT explicit REAL credential" in src
    assert "shared KIWOOM_USE_MOCK=true allowed" in src


# --- 7 LIVE preflight ---


def test_7_live_preflight_execution_uses_credential_not_global_mock() -> None:
    from stock_platform.broker.kiwoom import live_preflight_service as mod

    src = inspect.getsource(mod)
    assert "kiwoom_execution_real_env_pass" in src
    assert "credential_is_mock" in src
    assert "kiwoom_use_mock is market/shared only" in src


# --- 8 ORDER preflight (native KIWOOM) ---


def test_8_order_preflight_separates_market_env() -> None:
    from stock_platform.broker.kiwoom.live_preflight_service import (
        evaluate_kiwoom_market_env,
    )

    src = inspect.getsource(evaluate_kiwoom_market_env)
    assert "market_use_mock" in src


# --- 9 OES alignment ---


def test_9_oes_live_safety_uses_option_d_bypass() -> None:
    from stock_platform.order import live_safety_pipeline as mod

    src = inspect.getsource(mod.LiveOrderSafetyPipeline.evaluate)
    assert "kiwoom_global_mock_blocks_live_execution" in src
    assert "LIVE_MOCK_CONFLICT" in src


# --- 10 Outbox dispatch alignment ---


def test_10_outbox_dispatch_uses_option_d_bypass() -> None:
    from stock_platform.order import outbox_dispatch_safety as mod

    src = inspect.getsource(mod.assert_live_outbox_dispatch_safety)
    assert "kiwoom_global_mock_blocks_live_execution" in src
    assert "user_broker_account_id" in src


# --- 11 adapter host from credential ---


def test_11_adapter_host_follows_credential_is_mock_not_env(monkeypatch) -> None:
    _option_d_env(monkeypatch)
    resolved = ResolvedBrokerCredential(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        credential_id=1,
        key_version=1,
        payload={
            "app_key": "k",
            "secret_key": "s",
            "is_mock": False,
        },
        verification_status="VERIFIED",
    )
    cfg = build_kiwoom_order_config_from_vault(resolved)
    assert cfg.base_url == KIWOOM_REAL_EXECUTION_BASE
    assert cfg.use_mock is False
    mock_resolved = ResolvedBrokerCredential(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        credential_id=2,
        key_version=1,
        payload={
            "app_key": "k",
            "secret_key": "s",
            "is_mock": True,
        },
        verification_status="VERIFIED",
    )
    mock_cfg = build_kiwoom_order_config_from_vault(mock_resolved)
    assert mock_cfg.base_url == KIWOOM_MOCK_EXECUTION_BASE
    assert kiwoom_execution_base_url(is_mock=False) == KIWOOM_REAL_EXECUTION_BASE


# --- 12 UPBIT regression ---


def test_12_upbit_ignores_kiwoom_use_mock(monkeypatch) -> None:
    _option_d_env(monkeypatch)
    result = evaluate_live_flag_consistency(broker_code="UPBIT")
    assert result.allowed is True
    assert result.code == "UPBIT_FLAGS_OK"
    assert result.detail.get("kiwoom_flags_ignored") is True


# --- 13 multi-UBA runner ---


def test_13_multi_uba_runner_keys_remain_tuple_scope() -> None:
    assert runner_scope_key(1380, "UPBIT") == (1380, "UPBIT")
    assert runner_scope_key(1381, "KIWOOM") == (1381, "KIWOOM")
    from stock_platform.realtime import execution_runner_manager as mgr_mod
    from stock_platform.realtime import execution_scope as scope_mod

    assert "runner_scope_key" in inspect.getsource(mgr_mod.RealtimeExecutionRunnerManager)
    assert "user_broker_account_id" in inspect.getsource(scope_mod)
    assert "broker_code" in inspect.getsource(scope_mod)


# --- 14 Option D regression ---


def test_14_option_d_explicit_real_helper_exists() -> None:
    src = inspect.getsource(kiwoom_uba_has_explicit_real_execution)
    assert "explicit" in src
    assert "is_mock is False" in src


# --- 15 Paper regression ---


def test_15_paper_factory_does_not_use_live_mock_conflict() -> None:
    src = inspect.getsource(BrokerAdapterFactory.create)
    paper_idx = src.index("BrokerEnvironment.PAPER")
    live_idx = src.index("LIVE_MOCK_CONFLICT")
    assert paper_idx < live_idx
    adapter = BrokerAdapterFactory.create(
        BrokerEnvironment.PAPER, "KIWOOM"
    )
    assert adapter.__class__.__name__ == "PaperBrokerAdapter"


# --- runtime gates: no UPBIT mutation, no LIVE_MOCK_CONFLICT on explicit REAL ---


def test_runtime_gates_do_not_mutate_upbit_and_omit_unscoped_conflict() -> None:
    src = inspect.getsource(evaluate_kiwoom_runtime_run_gates)
    assert "pause_upbit" not in src
    assert "mutates_upbit" in src
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        is_active=True,
        deleted_at=None,
        connection_status="CONNECTED",
        live_order_enabled=False,
        live_armed=False,
        arm_expires_at=None,
    )
    session.get.return_value = uba
    with patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates.assert_uba_connection_ready",
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates._credential_verified",
        return_value=(True, "VERIFIED"),
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates.assert_recovery_ready",
        return_value={"recovery_status": "SUCCESS", "trading_paused": False},
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates.assert_risk_account_not_paused",
        return_value={"account_paused": False},
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates._kill_active_kiwoom",
        return_value=False,
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates._activation_active_kiwoom",
        return_value={"ok": False},
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates._arm_effective",
        return_value=(False, {"arm": "EXPIRED"}),
    ), patch(
        "stock_platform.realtime.kiwoom_runtime_run_gates.live_outbox_queue_block_reason",
        return_value=None,
    ), patch(
        "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
        return_value=SimpleNamespace(
            code="KIWOOM_EXPLICIT_REAL_EXECUTION",
            status="DEGRADED",
            allowed=True,
        ),
    ), patch(
        "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime"
    ) as worker:
        worker.status.return_value = {"enabled": True, "running": True}
        result = evaluate_kiwoom_runtime_run_gates(
            session, user_broker_account_id=1381
        )
    assert result["checks"].get("mutates_upbit") is False
    assert "LIVE_MOCK_CONFLICT" not in result["blockers"]
    assert "LIVE_OFF" in result["blockers"]
    assert "ACTIVATION_INACTIVE" in result["blockers"]
