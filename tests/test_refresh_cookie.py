"""Refresh cookie helper 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

from stock_platform.auth.refresh_cookie import (
    REFRESH_COOKIE_NAME,
    clear_refresh_cookie,
    read_refresh_token,
    set_refresh_cookie,
)


def test_read_prefers_body() -> None:
    request = MagicMock()
    request.cookies = {REFRESH_COOKIE_NAME: "cookie-token"}
    assert read_refresh_token(request, "body-token") == "body-token"


def test_set_cookie_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_REFRESH_COOKIE_ENABLED", "false")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        response = MagicMock()
        set_refresh_cookie(response, "tok")
        response.set_cookie.assert_not_called()
    finally:
        get_settings.cache_clear()


def test_clear_cookie_always() -> None:
    response = MagicMock()
    clear_refresh_cookie(response)
    response.delete_cookie.assert_called()
