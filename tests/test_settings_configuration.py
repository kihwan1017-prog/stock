"""STEP3 — Settings / env 로딩 / import 안전성."""

from __future__ import annotations

import importlib
import sys

import pytest

from stock_platform.common.settings import (
    Settings,
    clear_settings_cache,
    format_jwt_secret_missing_message,
    get_settings,
    is_testing_runtime,
    resolve_env_file,
)


def _isolated(**overrides) -> Settings:
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


@pytest.mark.unit
def test_is_testing_runtime_under_pytest() -> None:
    assert is_testing_runtime() is True


@pytest.mark.unit
def test_disable_env_file(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_PLATFORM_DISABLE_ENV_FILE", "true")
    monkeypatch.delenv("STOCK_PLATFORM_ENV_FILE", raising=False)
    assert resolve_env_file() is None


@pytest.mark.unit
def test_explicit_env_file_wins(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / "custom.env"
    env_path.write_text(
        "DB_HOST=localhost\n"
        "DB_NAME=stock_platform\n"
        "DB_USER=stock_app\n"
        "DB_PASSWORD=test\n"
        "JWT_SECRET=from-file-secret-value-32chars\n"
        "KIWOOM_LIVE_ORDER_ENABLED=true\n"
        "KIWOOM_USE_MOCK=false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STOCK_PLATFORM_ENV_FILE", str(env_path))
    monkeypatch.delenv("STOCK_PLATFORM_DISABLE_ENV_FILE", raising=False)
    # 프로세스 Live 오버라이드 제거 — 파일 값 검증용
    monkeypatch.delenv("KIWOOM_LIVE_ORDER_ENABLED", raising=False)
    monkeypatch.delenv("KIWOOM_USE_MOCK", raising=False)

    clear_settings_cache()
    settings = get_settings()
    assert settings.jwt_secret.startswith("from-file")
    assert settings.kiwoom_live_order_enabled is True
    assert settings.kiwoom_use_mock is False


@pytest.mark.unit
def test_jwt_secret_key_alias(monkeypatch) -> None:
    """구명칭 JWT_SECRET_KEY 도 읽는다."""

    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv(
        "JWT_SECRET_KEY",
        "legacy-secret-key-value-32chars!!",
    )
    settings = Settings(
        _env_file=None,
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
    )
    assert settings.jwt_secret == "legacy-secret-key-value-32chars!!"


@pytest.mark.unit
def test_missing_db_raises_without_env_file() -> None:
    with pytest.raises(Exception):
        Settings(_env_file=None)


@pytest.mark.unit
def test_prod_requires_admin_api_key() -> None:
    settings = _isolated(
        app_env="prod",
        admin_api_key="",
        cors_allow_origins="https://admin.example.com",
    )
    with pytest.raises(ValueError, match="ADMIN_API_KEY"):
        settings.validate_startup()


@pytest.mark.unit
def test_prod_rejects_localhost_only_cors() -> None:
    settings = _isolated(
        app_env="staging",
        admin_api_key="prod-admin-key",
        cors_allow_origins="http://localhost:3000",
    )
    with pytest.raises(ValueError, match="CORS_ALLOW_ORIGINS"):
        settings.validate_startup()


@pytest.mark.unit
def test_local_startup_ok_without_admin_key() -> None:
    settings = _isolated(app_env="local", admin_api_key="")
    settings.validate_startup()


@pytest.mark.unit
def test_live_mock_conflict_rejected() -> None:
    settings = _isolated(
        kiwoom_live_order_enabled=True,
        kiwoom_use_mock=True,
    )
    with pytest.raises(ValueError, match="KIWOOM_LIVE"):
        settings.validate_startup()


@pytest.mark.unit
def test_security_defaults_isolated() -> None:
    settings = _isolated()
    assert settings.kiwoom_live_order_enabled is False
    assert settings.upbit_live_order_enabled is False
    assert settings.global_live_order_enabled is False
    assert settings.kiwoom_use_mock is True
    assert settings.upbit_use_mock is True


@pytest.mark.unit
def test_get_settings_respects_live_env_override(monkeypatch) -> None:
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    clear_settings_cache()
    settings = get_settings()
    assert settings.kiwoom_live_order_enabled is False
    assert settings.kiwoom_use_mock is True


@pytest.mark.unit
def test_jwt_missing_message_mentions_alias() -> None:
    message = format_jwt_secret_missing_message()
    assert "JWT_SECRET" in message
    assert "JWT_SECRET_KEY" in message


@pytest.mark.unit
def test_notification_runtime_import_is_lazy() -> None:
    """runtime 모듈 import 만으로 get_settings 가 강제되지 않아야 한다."""

    mod_name = "stock_platform.notification.runtime"
    sys.modules.pop(mod_name, None)
    module = importlib.import_module(mod_name)
    assert module._risk_notification_sender is None
    assert module._notification_service is None


@pytest.mark.unit
def test_realtime_runtime_import_without_settings() -> None:
    """realtime.runtime import 시 Settings 로드 없이 runner 기본 계좌 1."""

    mod_name = "stock_platform.realtime.runtime"
    # 이미 로드됐을 수 있으므로 속성만 검증
    from stock_platform.realtime import runtime as rt

    assert rt.realtime_execution_runner._config.account_id == 1


@pytest.mark.unit
def test_clear_settings_cache(monkeypatch) -> None:
    clear_settings_cache()
    first = get_settings()
    monkeypatch.setenv("APP_NAME", "after-clear")
    clear_settings_cache()
    second = get_settings()
    assert second.app_name == "after-clear"
    assert first is not second
