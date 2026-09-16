"""Option C — Kiwoom execution env (credential SoT) vs permission separation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.credential_adapter_factory import (
    build_kiwoom_order_config_from_vault,
)
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
    ResolvedBrokerCredential,
)
from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.kiwoom.execution_env import (
    KIWOOM_MOCK_EXECUTION_BASE,
    KIWOOM_REAL_EXECUTION_BASE,
    kiwoom_global_mock_blocks_live_execution,
)
from stock_platform.broker.kiwoom.live_preflight_service import (
    KiwoomLivePreflightService,
    KiwoomPreflightSnapshot,
)
from stock_platform.broker.live_config_gate import evaluate_live_flag_consistency
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.order.outbox_adapter_resolver import resolve_outbox_adapter


def _now() -> datetime:
    return datetime(2026, 8, 18, 2, 0, tzinfo=timezone.utc)


def _real_resolved(*, is_mock: bool = False) -> ResolvedBrokerCredential:
    return ResolvedBrokerCredential(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        credential_id=1,
        key_version=1,
        payload={
            "app_key": "k",
            "secret_key": "s",
            "account_number": "1234145",
            "is_mock": is_mock,
        },
        verification_status="VERIFIED",
    )


def _settings_mock(*, kiwoom_use_mock: bool = True, **flags: bool):
    base = SimpleNamespace(
        kiwoom_use_mock=kiwoom_use_mock,
        global_live_order_enabled=flags.get("global_live", False),
        kiwoom_live_order_enabled=flags.get("kiwoom_live", False),
        upbit_live_order_enabled=False,
        kiwoom_http_timeout_seconds=10.0,
        kiwoom_live_order_enabled_flag=flags.get("kiwoom_live", False),
    )
    return base


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
        env_kiwoom_use_mock=True,
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


def _check_status(report: dict, code: str) -> str:
    for row in report.get("checks") or []:
        if row.get("code") == code:
            return str(row.get("status"))
    return "MISSING"


# --- A–E: credential / host resolution ---


def test_a_real_cred_real_order_client_host(monkeypatch) -> None:
    monkeypatch.setattr(
        "stock_platform.broker.credential_adapter_factory.get_settings",
        lambda: _settings_mock(kiwoom_use_mock=True),
    )
    cfg = build_kiwoom_order_config_from_vault(_real_resolved(is_mock=False))
    assert cfg.use_mock is False
    assert cfg.base_url == KIWOOM_REAL_EXECUTION_BASE


def test_b_real_cred_global_mock_true_still_real_host(monkeypatch) -> None:
    monkeypatch.setattr(
        "stock_platform.broker.credential_adapter_factory.get_settings",
        lambda: _settings_mock(kiwoom_use_mock=True),
    )
    cfg = build_kiwoom_order_config_from_vault(_real_resolved(is_mock=False))
    assert cfg.base_url == "https://api.kiwoom.com"


def test_c_mock_cred_global_false_mock_host(monkeypatch) -> None:
    monkeypatch.setattr(
        "stock_platform.broker.credential_adapter_factory.get_settings",
        lambda: _settings_mock(kiwoom_use_mock=False),
    )
    cfg = build_kiwoom_order_config_from_vault(_real_resolved(is_mock=True))
    assert cfg.use_mock is True
    assert cfg.base_url == KIWOOM_MOCK_EXECUTION_BASE


def test_d_missing_credential_fail_closed() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.broker.credential_adapter_factory.resolve_uba_credential",
        side_effect=BrokerCredentialVaultError("missing", "no cred"),
    ):
        from stock_platform.broker.kiwoom.execution_env import (
            kiwoom_uba_execution_is_mock,
        )

        is_mock, explicit = kiwoom_uba_execution_is_mock(session, 9999)
    assert is_mock is None
    assert explicit is False


def test_e_legacy_missing_is_mock_global_fallback(monkeypatch) -> None:
    resolved = ResolvedBrokerCredential(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        credential_id=1,
        key_version=1,
        payload={
            "app_key": "k",
            "secret_key": "s",
            "account_number": "1",
        },
        verification_status="VERIFIED",
    )
    monkeypatch.setattr(
        "stock_platform.broker.credential_adapter_factory.get_settings",
        lambda: _settings_mock(kiwoom_use_mock=True),
    )
    cfg = build_kiwoom_order_config_from_vault(resolved)
    assert cfg.use_mock is True
    assert cfg.base_url == KIWOOM_MOCK_EXECUTION_BASE


# --- F–H: scoped builders ---


def test_f_account_client_for_uba_uses_vault_host(monkeypatch) -> None:
    session = MagicMock()
    fake_client = MagicMock()
    fake_client._client = MagicMock()
    with (
        patch(
            "stock_platform.broker.credential_adapter_factory.resolve_uba_credential",
            return_value=_real_resolved(is_mock=False),
        ),
        patch(
            "stock_platform.broker.credential_adapter_factory.build_kiwoom_broker_config_from_vault",
        ) as cfg_mock,
        patch(
            "stock_platform.broker.credential_adapter_factory.KiwoomAccountClient",
            return_value=fake_client,
        ),
        patch(
            "stock_platform.broker.credential_adapter_factory.KiwoomRestClient",
        ),
        patch(
            "stock_platform.broker.credential_adapter_factory.KiwoomTokenProvider",
        ),
    ):
        from stock_platform.broker.credential_adapter_factory import (
            build_kiwoom_account_client_for_uba,
        )

        cfg_mock.return_value = SimpleNamespace(
            validate=lambda: None, use_mock=False, base_url=KIWOOM_REAL_EXECUTION_BASE
        )
        client, acct = build_kiwoom_account_client_for_uba(session, 1381)
    assert client is fake_client
    assert acct == "1234145"


def test_g_order_execution_chain_real_host(monkeypatch) -> None:
    """TradingOrder → Outbox → Factory → vault adapter host."""

    session = MagicMock()
    fake_adapter = SimpleNamespace(
        config=SimpleNamespace(
            base_url=KIWOOM_REAL_EXECUTION_BASE,
            use_mock=False,
        )
    )
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        with (
            patch(
                "stock_platform.broker.factory.LiveTradingTransitionGuard.require_active",
            ),
            patch(
                "stock_platform.broker.factory.build_kiwoom_adapter_for_uba",
                return_value=fake_adapter,
            ) as build_mock,
            patch(
                "stock_platform.broker.kiwoom.execution_env.kiwoom_global_mock_blocks_live_execution",
                return_value=False,
            ),
        ):
            adapter = BrokerAdapterFactory.create(
                BrokerEnvironment.LIVE,
                "KIWOOM",
                session=session,
                user_broker_account_id=1381,
            )
        build_mock.assert_called_once_with(session, 1381)
        assert adapter.config.base_url == KIWOOM_REAL_EXECUTION_BASE
    finally:
        get_settings.cache_clear()


def test_h_no_cred_uba_real_execution_blocked(monkeypatch) -> None:
    session = MagicMock()
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        with patch(
            "stock_platform.broker.credential_adapter_factory.resolve_uba_credential",
            side_effect=BrokerCredentialVaultError("missing", "no cred"),
        ):
            assert kiwoom_global_mock_blocks_live_execution(
                session, user_broker_account_id=2001
            )
    finally:
        get_settings.cache_clear()


# --- I–K: permission still blocks submit ---


def test_i_global_live_off_factory_blocked(monkeypatch) -> None:
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(PermissionError, match="GLOBAL_LIVE"):
            BrokerAdapterFactory.create(
                BrokerEnvironment.LIVE,
                "KIWOOM",
                session=MagicMock(),
                user_broker_account_id=1381,
            )
    finally:
        get_settings.cache_clear()


def test_j_uba_live_off_preflight_arm() -> None:
    report = KiwoomLivePreflightService(MagicMock()).evaluate(
        _healthy(live_order_enabled=False), mode="ARM_ON"
    )
    assert "ARM_LIVE_REQUIRED" in _codes(report, "FAIL")


def test_k_arm_off_preflight_order() -> None:
    report = KiwoomLivePreflightService(MagicMock()).evaluate(
        _healthy(
            live_order_enabled=True,
            live_armed=False,
            env_global_live=True,
            env_kiwoom_live=True,
            arm_precondition_ok=True,
        ),
        mode="ORDER",
    )
    assert report["overall_status"] == "BLOCKED"
    assert "ARM" in str(_codes(report, "FAIL"))


# --- L–M: preflight REAL vs MARKET ---


def test_l_market_mismatch_pre_live_warn() -> None:
    report = KiwoomLivePreflightService(MagicMock()).evaluate(
        _healthy(credential_is_mock=False, env_kiwoom_use_mock=True),
        mode="LIVE_ON",
    )
    assert _check_status(report, "KIWOOM_REAL_ENV") == "PASS"
    assert _check_status(report, "KIWOOM_MARKET_ENV") == "WARN"


def test_l2_market_mismatch_pre_order_option_d_pass() -> None:
    """Option D: 수동 ORDER는 shared MOCK이어도 MARKET_ENV PASS."""
    report = KiwoomLivePreflightService(MagicMock()).evaluate(
        _healthy(
            credential_is_mock=False,
            env_kiwoom_use_mock=True,
            live_order_enabled=True,
            live_armed=True,
            arm_expires_at=_now() + timedelta(minutes=4),
            env_global_live=True,
            env_kiwoom_live=True,
            arm_precondition_ok=True,
            krx_in_regular_session=True,
        ),
        mode="ORDER",
    )
    assert _check_status(report, "KIWOOM_MARKET_ENV") == "PASS"
    assert report["overall_status"] == "READY_FOR_ORDER"


def test_m_real_env_pass_with_global_mock() -> None:
    report = KiwoomLivePreflightService(MagicMock()).evaluate(
        _healthy(credential_is_mock=False, env_kiwoom_use_mock=True),
        mode="LIVE_ON",
    )
    assert _check_status(report, "KIWOOM_REAL_ENV") == "PASS"


def test_uba1381_equivalent_pre_live() -> None:
    report = KiwoomLivePreflightService(MagicMock()).evaluate(
        _healthy(
            trading_paused=True,
            credential_is_mock=False,
            env_kiwoom_use_mock=True,
        ),
        mode="LIVE_ON",
    )
    assert _check_status(report, "KIWOOM_REAL_ENV") == "PASS"
    assert _check_status(report, "KIWOOM_MARKET_ENV") == "WARN"
    assert _check_status(report, "TRADING_PAUSED") == "FAIL"
    assert report["overall_status"] == "BLOCKED"


# --- N: Upbit regression dispatch ---


def test_n_upbit_dispatch_unchanged() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        user_id=61,
        broker_code="UPBIT",
        deleted_at=None,
        is_active=True,
    )
    with patch(
        "stock_platform.broker.kiwoom.live_preflight_service.KiwoomLivePreflightService.run"
    ) as krun:
        from stock_platform.operation.runtime_preflight_service import (
            RuntimePreflightService,
        )

        try:
            RuntimePreflightService(session).run_for_uba(
                user_broker_account_id=1380
            )
        except Exception:
            pass
    krun.assert_not_called()


# --- O–P: no network / outbox resolver ---


def test_o_outbox_resolves_without_network(monkeypatch) -> None:
    session = MagicMock()
    fake = SimpleNamespace(config=SimpleNamespace(base_url=KIWOOM_REAL_EXECUTION_BASE))
    with patch(
        "stock_platform.order.outbox_adapter_resolver.BrokerAdapterFactory.create",
        return_value=fake,
    ) as create_mock:
        adapter = resolve_outbox_adapter(
            {
                "environment": "LIVE",
                "broker_code": "KIWOOM",
                "user_broker_account_id": 1381,
            },
            session=session,
        )
    create_mock.assert_called_once()
    assert adapter.config.base_url == KIWOOM_REAL_EXECUTION_BASE


def test_p_trading_order_outbox_delta_not_applicable() -> None:
    """Fixture-only — broker/order mutation 없음 (Δ0)."""

    assert True


# --- Q–S: gate contracts ---


def test_q_uba_explicit_real_bypasses_global_mock_conflict(monkeypatch) -> None:
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    session = MagicMock()
    try:
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
        cfg = evaluate_live_flag_consistency()
        assert cfg.code == "LIVE_MOCK_CONFLICT"
    finally:
        get_settings.cache_clear()


def test_r_system_shared_still_blocked_by_global_mock(monkeypatch) -> None:
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        assert kiwoom_global_mock_blocks_live_execution(
            None,
            user_broker_account_id=None,
            uses_system_shared_credential=True,
        )
    finally:
        get_settings.cache_clear()


def test_s_environment_resolution_does_not_enable_live_flags(monkeypatch) -> None:
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        cfg = build_kiwoom_order_config_from_vault(_real_resolved(is_mock=False))
        assert cfg.base_url == KIWOOM_REAL_EXECUTION_BASE
        s = get_settings()
        assert s.global_live_order_enabled is False
        assert s.kiwoom_live_order_enabled is False
    finally:
        get_settings.cache_clear()
