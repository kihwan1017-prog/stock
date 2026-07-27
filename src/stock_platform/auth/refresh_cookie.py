"""Refresh Token HttpOnly Cookie 헬퍼 (선택 활성화)."""

from __future__ import annotations

from fastapi import Request, Response

from stock_platform.common.settings import get_settings

REFRESH_COOKIE_NAME = "kiki_refresh_token"


def refresh_cookie_enabled() -> bool:
    return bool(get_settings().auth_refresh_cookie_enabled)


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    if not refresh_cookie_enabled():
        return
    settings = get_settings()
    max_age = int(settings.jwt_refresh_token_expire_days) * 86400
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=bool(settings.is_production_env),
        samesite="lax",
        max_age=max_age,
        path="/api/v1/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/api/v1/auth",
    )


def read_refresh_token(
    request: Request,
    body_token: str | None,
) -> str | None:
    """Body 우선, 없으면 HttpOnly cookie."""

    if body_token and str(body_token).strip():
        return str(body_token).strip()
    if not refresh_cookie_enabled():
        return None
    return request.cookies.get(REFRESH_COOKIE_NAME)
