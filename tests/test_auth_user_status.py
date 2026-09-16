"""통합 로그인 상태·default_route·잠금 단위 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from stock_platform.auth.user_status import (
    STATUS_ACTIVE,
    STATUS_INACTIVE,
    STATUS_LOCKED,
    STATUS_PASSWORD_CHANGE_REQUIRED,
    resolve_default_route,
    resolve_user_status,
)


def _user(**kwargs):
    base = dict(
        deleted_at=None,
        is_active=True,
        locked_until=None,
        password_change_required=False,
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_resolve_status_active() -> None:
    assert resolve_user_status(_user()) == STATUS_ACTIVE


def test_resolve_status_inactive() -> None:
    assert resolve_user_status(_user(is_active=False)) == STATUS_INACTIVE


def test_resolve_status_locked() -> None:
    until = datetime.now(timezone.utc) + timedelta(minutes=10)
    assert resolve_user_status(_user(locked_until=until)) == STATUS_LOCKED


def test_resolve_status_password_change() -> None:
    assert (
        resolve_user_status(_user(password_change_required=True))
        == STATUS_PASSWORD_CHANGE_REQUIRED
    )


def test_default_route_admin() -> None:
    route = resolve_default_route(
        user=_user(),
        roles=["admin"],
    )
    assert route == "/admin/dashboard"


def test_default_route_user() -> None:
    route = resolve_default_route(
        user=_user(),
        roles=["user"],
    )
    assert route == "/user/dashboard"


def test_default_route_password_change() -> None:
    route = resolve_default_route(
        user=_user(password_change_required=True),
        roles=["user"],
    )
    assert route == "/change-password"


def test_default_route_onboarding() -> None:
    route = resolve_default_route(
        user=_user(onboarding_completed_at=None),
        roles=["user"],
    )
    assert route == "/onboarding"


def test_admin_skips_onboarding() -> None:
    route = resolve_default_route(
        user=_user(onboarding_completed_at=None),
        roles=["admin"],
    )
    assert route == "/admin/dashboard"


def test_default_route_legacy_viewer_alias() -> None:
    route = resolve_default_route(
        user=_user(),
        roles=["viewer"],
    )
    assert route == "/user/dashboard"


def test_default_route_invalid_roles_forbidden() -> None:
    assert (
        resolve_default_route(user=_user(), roles=[]) == "/forbidden"
    )
    assert (
        resolve_default_route(user=_user(), roles=["guest"])
        == "/forbidden"
    )
