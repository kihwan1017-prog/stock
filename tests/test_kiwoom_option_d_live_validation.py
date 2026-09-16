"""Option D — Kiwoom LIVE + shared MOCK validation alignment.

broker 네트워크 없음. production Activation / LIVE / ARM / env 변경 없음.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.kiwoom.execution_env import (
    kiwoom_global_mock_blocks_live_execution,
)
from stock_platform.broker.kiwoom.live_preflight_service import (
    KiwoomLivePreflightService,
)
from stock_platform.broker.live_config_gate import evaluate_live_flag_consistency
from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)
from stock_platform.broker.live_transition_validators import (
    KiwoomLiveTransitionValidator,
)
from stock_platform.common.settings import Settings, get_settings
from stock_platform.operation.setting_catalog import DEFINITION_BY_KEY
from stock_platform.operation.setting_service import AppSettingService
from tests.test_kiwoom_market_env_option_d import _order_ready


def _isolated_settings(**overrides) -> Settings:
    base = {
        "db_host": "localhost",
        "db_name": "stock_platform",
        "db_user": "stock_app",
        "db_password": "test",
        "jwt_secret": "unit-test-secret-value-32chars!!",
        "app_env": "local",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _option_d_live_env(
    monkeypatch,
    *,
    account_number: str = "",
    ws_json: str = "",
) -> None:
    """Target Option D process flags. env 계좌/WS 는 기본 비움 (vault SoT)."""

    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    monkeypatch.setenv("KIWOOM_ACCOUNT_NUMBER", account_number)
    monkeypatch.setenv("KIWOOM_APP_KEY", "key")
    monkeypatch.setenv("KIWOOM_SECRET_KEY", "secret")
    monkeypatch.setenv("KIWOOM_ORDER_WS_SUBSCRIBE_JSON", ws_json)
    monkeypatch.setenv("KIWOOM_RECOVERY_START_TRADING", "false")
    get_settings.cache_clear()


def _uba(
    *,
    uba_id: int = 1381,
    broker: str = "KIWOOM",
    active: bool = True,
):
    return SimpleNamespace(
        user_broker_account_id=uba_id,
        user_id=61,
        broker_code=broker,
        is_active=active,
        deleted_at=None,
        connection_status="CONNECTED",
    )


def _cred_status(
    *,
    verified: bool = True,
    present: bool = True,
    is_mock: bool | None = False,
    broker: str = "KIWOOM",
    active: bool | None = None,
):
    ver = "VERIFIED" if verified else "PENDING"
    if not present:
        ver = None
    is_active = present if active is None else active
    return SimpleNamespace(
        is_active=is_active,
        connected=present,
        verification_status=ver,
        is_mock=is_mock,
        broker_code=broker,
    )


def _session_with_uba(uba) -> MagicMock:
    session = MagicMock()

    def _get(_model, pk, *args, **kwargs):
        if uba is None:
            return None
        try:
            key = int(pk)
        except (TypeError, ValueError):
            return None
        if int(uba.user_broker_account_id) == key:
            return uba
        return None

    session.get.side_effect = _get
    return session


def _validate_account(
    session,
    *,
    uba_id: int | None = 1381,
    scope: str = "ACCOUNT",
):
    return KiwoomLiveTransitionValidator(session).validate(
        max_order_amount=Decimal("10000"),
        max_daily_loss=Decimal("50000"),
        paper_validation_approved=True,
        scope=scope,
        user_broker_account_id=uba_id,
    )


def _fail_codes(plan) -> set[str]:
    return {c.code.value for c in plan.checks if c.status.value == "FAIL"}


def _check(plan, code: str) -> str:
    for row in plan.checks:
        if row.code.value == code:
            return row.status.value
    return "MISSING"


def _check_message(plan, code: str) -> str:
    for row in plan.checks:
        if row.code.value == code:
            return row.message
    return ""


def _assert_legacy_env_gates_fail(plan) -> None:
    """eligibility 미달 시 env 계좌/WS 를 무조건 PASS 하면 안 된다."""

    assert _check(plan, "ACCOUNT_NUMBER_PRESENT") == "FAIL"
    assert _check(plan, "WEBSOCKET_CONFIGURED") == "FAIL"


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- A–D startup / catalog ---


def test_a_kiwoom_live_shared_mock_startup_pass() -> None:
    settings = _isolated_settings(
        global_live_order_enabled=True,
        kiwoom_live_order_enabled=True,
        kiwoom_use_mock=True,
        upbit_live_order_enabled=False,
        upbit_use_mock=False,
    )
    settings.validate_startup()


def test_b_upbit_live_mock_startup_fail() -> None:
    settings = _isolated_settings(
        upbit_live_order_enabled=True,
        upbit_use_mock=True,
    )
    with pytest.raises(ValueError, match="UPBIT_LIVE"):
        settings.validate_startup()


def test_c_catalog_kiwoom_live_mock_accepted() -> None:
    AppSettingService(MagicMock(), settings=MagicMock())._validate_trading_cross(
        {
            "kiwoom_use_mock": "true",
            "kiwoom_live_order_enabled": "true",
        }
    )


def test_d_catalog_upbit_live_mock_rejected() -> None:
    """Upbit LIVE 키는 catalog 에 없고, startup 규칙은 기존 FAIL."""

    assert "upbit_live_order_enabled" not in DEFINITION_BY_KEY
    assert "upbit_use_mock" not in DEFINITION_BY_KEY
    settings = _isolated_settings(
        upbit_live_order_enabled=True,
        upbit_use_mock=True,
    )
    with pytest.raises(ValueError, match="UPBIT_LIVE"):
        settings.validate_startup()


# --- E–I Activation validator ---


def test_e_account_explicit_real_activation_pass(monkeypatch) -> None:
    """A: ACCOUNT + VERIFIED + is_mock=false + env 계좌/WS 비움 → ready."""

    _option_d_live_env(monkeypatch)
    session = _session_with_uba(_uba())
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        vault_cls.return_value.status.return_value = _cred_status(is_mock=False)
        plan = _validate_account(session)
    assert plan.ready is True
    assert plan.scope == "ACCOUNT"
    assert plan.user_broker_account_id == 1381
    assert _check(plan, "MOCK_MODE_DISABLED") == "PASS"
    assert _check(plan, "ACCOUNT_NUMBER_PRESENT") == "PASS"
    assert _check(plan, "WEBSOCKET_CONFIGURED") == "PASS"
    assert "UBA credential-scoped account configuration" in _check_message(
        plan, "ACCOUNT_NUMBER_PRESENT"
    )
    assert "Shared websocket not required" in _check_message(
        plan, "WEBSOCKET_CONFIGURED"
    )
    assert _check(plan, "APP_CREDENTIALS_PRESENT") == "PASS"
    vault_cls.return_value.status.assert_called()


def test_f_account_missing_credential_fail(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = _session_with_uba(_uba())
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        vault_cls.return_value.status.return_value = _cred_status(
            verified=False,
            present=False,
            is_mock=None,
        )
        plan = _validate_account(session)
    assert plan.ready is False
    assert "CREDENTIAL_PRESENT" in _fail_codes(plan)
    assert "MOCK_MODE_DISABLED" in _fail_codes(plan)
    _assert_legacy_env_gates_fail(plan)


def test_g_account_mock_credential_fail(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = _session_with_uba(_uba())
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        vault_cls.return_value.status.return_value = _cred_status(is_mock=True)
        plan = _validate_account(session)
    assert plan.ready is False
    assert _check(plan, "CREDENTIAL_VERIFIED") == "PASS"
    assert "MOCK_MODE_DISABLED" in _fail_codes(plan)
    _assert_legacy_env_gates_fail(plan)


def test_h_account_unknown_is_mock_fail(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = _session_with_uba(_uba())
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        vault_cls.return_value.status.return_value = _cred_status(is_mock=None)
        plan = _validate_account(session)
    assert plan.ready is False
    assert "MOCK_MODE_DISABLED" in _fail_codes(plan)
    _assert_legacy_env_gates_fail(plan)


def test_i_broker_scope_shared_mock_fail(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = _session_with_uba(_uba())
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        vault_cls.return_value.status.return_value = _cred_status(is_mock=False)
        plan = _validate_account(session, uba_id=1381, scope="BROKER")
    assert plan.ready is False
    assert "MOCK_MODE_DISABLED" in _fail_codes(plan)
    _assert_legacy_env_gates_fail(plan)
    vault_cls.assert_not_called()


def test_account_unverified_credential_fail(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = _session_with_uba(_uba())
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        vault_cls.return_value.status.return_value = _cred_status(
            verified=False,
            present=True,
            is_mock=False,
        )
        plan = _validate_account(session)
    assert plan.ready is False
    assert "CREDENTIAL_VERIFIED" in _fail_codes(plan)
    assert "MOCK_MODE_DISABLED" in _fail_codes(plan)
    _assert_legacy_env_gates_fail(plan)


def test_account_wrong_broker_fail(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = _session_with_uba(_uba(broker="UPBIT"))
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        vault_cls.return_value.status.return_value = _cred_status(is_mock=False)
        plan = _validate_account(session)
    assert plan.ready is False
    assert "UBA_BROKER_MATCH" in _fail_codes(plan)
    assert "MOCK_MODE_DISABLED" in _fail_codes(plan)
    _assert_legacy_env_gates_fail(plan)


def test_account_missing_uba_fail(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = _session_with_uba(None)
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        plan = _validate_account(session)
    assert plan.ready is False
    assert "UBA_EXISTS" in _fail_codes(plan)
    vault_cls.assert_not_called()
    _assert_legacy_env_gates_fail(plan)


def test_account_inactive_uba_fail(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = _session_with_uba(_uba(active=False))
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        vault_cls.return_value.status.return_value = _cred_status(is_mock=False)
        plan = _validate_account(session)
    assert plan.ready is False
    assert "UBA_ACTIVE" in _fail_codes(plan)
    assert "MOCK_MODE_DISABLED" in _fail_codes(plan)
    _assert_legacy_env_gates_fail(plan)


def test_account_inactive_credential_fail(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = _session_with_uba(_uba())
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        vault_cls.return_value.status.return_value = _cred_status(
            is_mock=False,
            active=False,
        )
        plan = _validate_account(session)
    assert plan.ready is False
    assert "CREDENTIAL_PRESENT" in _fail_codes(plan)
    assert "MOCK_MODE_DISABLED" in _fail_codes(plan)
    _assert_legacy_env_gates_fail(plan)


def test_account_credential_broker_mismatch_fail(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = _session_with_uba(_uba())
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        vault_cls.return_value.status.return_value = _cred_status(
            is_mock=False,
            broker="UPBIT",
        )
        plan = _validate_account(session)
    assert plan.ready is False
    assert "CREDENTIAL_PRESENT" in _fail_codes(plan)
    assert "MOCK_MODE_DISABLED" in _fail_codes(plan)
    _assert_legacy_env_gates_fail(plan)


def test_system_shared_scope_fail_closed(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = _session_with_uba(_uba())
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        vault_cls.return_value.status.return_value = _cred_status(is_mock=False)
        plan = _validate_account(session, uba_id=1381, scope="SYSTEM_SHARED")
    assert plan.ready is False
    assert "MOCK_MODE_DISABLED" in _fail_codes(plan)
    _assert_legacy_env_gates_fail(plan)
    vault_cls.assert_not_called()


def test_account_1381_does_not_validate_other_uba(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = _session_with_uba(_uba(uba_id=1381))
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
    ) as vault_cls:
        vault_cls.return_value.status.return_value = _cred_status(is_mock=False)
        plan = _validate_account(session, uba_id=9999)
    assert plan.ready is False
    assert "UBA_EXISTS" in _fail_codes(plan)
    vault_cls.assert_not_called()
    _assert_legacy_env_gates_fail(plan)


# --- J–K MARKET_ENV ---


def test_j_manual_option_d_market_env_pass() -> None:
    report = KiwoomLivePreflightService(MagicMock()).evaluate(
        _order_ready(env_kiwoom_use_mock=True),
        mode="ORDER",
    )
    row = next(c for c in report["checks"] if c.get("code") == "KIWOOM_MARKET_ENV")
    assert row["status"] == "PASS"
    assert report["manual_order_allowed"] is True


def test_k_auto_option_d_market_env_fail() -> None:
    report = KiwoomLivePreflightService(MagicMock()).evaluate(
        _order_ready(env_kiwoom_use_mock=True),
        mode="SCHEDULER_RUN",
    )
    row = next(c for c in report["checks"] if c.get("code") == "KIWOOM_MARKET_ENV")
    assert row["status"] == "FAIL"
    assert report["overall_status"] == "BLOCKED"


# --- L–N isolation ---


def test_l_system_shared_real_order_blocked(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    assert kiwoom_global_mock_blocks_live_execution(
        None,
        user_broker_account_id=None,
        uses_system_shared_credential=True,
    ) is True
    assert kiwoom_global_mock_blocks_live_execution(
        None,
        user_broker_account_id=None,
        credential_ref="SYSTEM_SHARED:KIWOOM",
    ) is True


def test_m_no_credential_uba_blocks_live_execution(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    session = MagicMock()
    with (
        patch(
            "stock_platform.broker.kiwoom.execution_env.kiwoom_uba_has_explicit_real_execution",
            return_value=False,
        ),
        patch(
            "stock_platform.broker.kiwoom.execution_env.kiwoom_uba_execution_is_mock",
            return_value=(None, False),
        ),
    ):
        assert kiwoom_global_mock_blocks_live_execution(
            session,
            user_broker_account_id=9999,
        ) is True


def test_n_other_uba_activation_isolation() -> None:
    entity = SimpleNamespace(
        broker_code="KIWOOM",
        scope="ACCOUNT",
        user_broker_account_id=1381,
        enabled=True,
    )
    assert (
        LiveTradingTransitionService.transition_matches_dispatch(
            entity,  # type: ignore[arg-type]
            broker_code="KIWOOM",
            user_broker_account_id=1381,
        )
        is True
    )
    assert (
        LiveTradingTransitionService.transition_matches_dispatch(
            entity,  # type: ignore[arg-type]
            broker_code="KIWOOM",
            user_broker_account_id=9999,
        )
        is False
    )


# --- O–P gate preservation ---


def test_o_upbit_startup_regression_isolated() -> None:
    kiwoom_ok = _isolated_settings(
        global_live_order_enabled=True,
        kiwoom_live_order_enabled=True,
        kiwoom_use_mock=True,
        upbit_live_order_enabled=False,
        upbit_use_mock=True,
    )
    kiwoom_ok.validate_startup()
    with pytest.raises(ValueError, match="UPBIT_LIVE"):
        _isolated_settings(
            upbit_live_order_enabled=True,
            upbit_use_mock=True,
        ).validate_startup()


def test_p_live_config_gate_conflict_signal_preserved(monkeypatch) -> None:
    _option_d_live_env(monkeypatch)
    result = evaluate_live_flag_consistency()
    assert result.code == "LIVE_MOCK_CONFLICT"
    assert result.allowed is False


def test_shared_ws_still_uses_env_settings() -> None:
    import inspect

    from stock_platform.broker.kiwoom.ws_runtime import (
        build_kiwoom_order_websocket,
    )

    source = inspect.getsource(build_kiwoom_order_websocket)
    assert "KiwoomBrokerConfig.from_settings()" in source


def test_shared_market_still_uses_kiwoom_use_mock() -> None:
    import inspect

    from stock_platform.broker.kiwoom.market import auth as market_auth

    source = inspect.getsource(market_auth)
    assert "kiwoom_use_mock" in source


def test_execution_adapter_remains_uba_vault_scoped() -> None:
    import inspect

    from stock_platform.broker.credential_adapter_factory import (
        build_kiwoom_adapter_for_uba,
        build_kiwoom_order_inquiry_client_for_uba,
    )

    adapter_src = inspect.getsource(build_kiwoom_adapter_for_uba)
    inquiry_src = inspect.getsource(build_kiwoom_order_inquiry_client_for_uba)
    assert "resolve_uba_credential" in adapter_src
    assert "build_kiwoom_order_config_from_vault" in adapter_src
    assert "build_kiwoom_order_http_client_for_uba" in inquiry_src
    assert "from_env" not in adapter_src
    assert "from_env" not in inquiry_src
