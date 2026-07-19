from __future__ import annotations

import pytest

from stock_platform.common.settings import (
    Settings,
    format_jwt_secret_missing_message,
)


def _settings(**overrides) -> Settings:
    base = {
        "db_host": "localhost",
        "db_name": "stock_platform",
        "db_user": "stock_app",
        "db_password": "test",
        "jwt_secret": "",
        "app_env": "local",
        "jwt_dev_auto_secret": True,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.mark.unit
def test_local_auto_generates_jwt_secret() -> None:
    settings = _settings(app_env="local", jwt_secret="")
    settings.validate_startup()
    assert settings.jwt_secret.strip()
    assert len(settings.jwt_secret) >= 32


@pytest.mark.unit
def test_prod_requires_jwt_secret() -> None:
    settings = _settings(app_env="prod", jwt_secret="")
    with pytest.raises(ValueError) as exc:
        settings.validate_startup()
    message = str(exc.value)
    assert "JWT_SECRET 환경변수가 없습니다" in message
    assert r"E:\StockTrading\secrets\stock-platform.env" in message
    assert "JWT_ALGORITHM=HS256" in message


@pytest.mark.unit
def test_local_with_auto_secret_disabled_fails() -> None:
    settings = _settings(
        app_env="local",
        jwt_secret="",
        jwt_dev_auto_secret=False,
    )
    with pytest.raises(ValueError) as exc:
        settings.validate_startup()
    assert "JWT_SECRET 환경변수가 없습니다" in str(exc.value)


@pytest.mark.unit
def test_prod_ignores_dev_auto_flag() -> None:
    settings = _settings(
        app_env="production",
        jwt_secret="",
        jwt_dev_auto_secret=True,
    )
    with pytest.raises(ValueError):
        settings.validate_startup()


@pytest.mark.unit
def test_friendly_message_helper() -> None:
    msg = format_jwt_secret_missing_message()
    assert "JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60" in msg
    assert "JWT_REFRESH_TOKEN_EXPIRE_DAYS=30" in msg
