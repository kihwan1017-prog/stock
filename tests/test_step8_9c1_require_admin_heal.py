"""require_admin — Session/Settings 실타입 + role heal → AuthenticatedUser."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from stock_platform.auth.deps import AuthenticatedUser, require_admin
from stock_platform.common.settings import get_settings


def _stub_session() -> Session:
    """isinstance(session, Session)만 통과시키는 스텁."""
    session = object.__new__(Session)
    session.commit = MagicMock()  # type: ignore[method-assign]
    return session


def test_require_admin_heals_jsonb_admin_without_user_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_api_key", "")
    user = SimpleNamespace(
        user_id=7,
        username="admin",
        is_active=True,
        roles=["admin"],
    )
    session = _stub_session()

    monkeypatch.setattr(
        "stock_platform.auth.deps.JwtTokenService",
        lambda _settings: SimpleNamespace(
            decode_access_token=lambda token: {"sub": "7"}
        ),
    )
    monkeypatch.setattr(
        "stock_platform.auth.deps.AuthRepository",
        lambda _session: SimpleNamespace(get_by_id=lambda user_id: user),
    )
    monkeypatch.setattr(
        "stock_platform.auth.deps.RbacRepository",
        lambda _session: MagicMock(),
    )
    monkeypatch.setattr(
        "stock_platform.auth.role_sync.reconcile_user_roles",
        lambda session, user, rbac, *, commit=False: (["admin"], True),
    )
    monkeypatch.setattr(
        "stock_platform.auth.role_sync.resolve_role_codes",
        lambda user, rbac=None: ["admin"],
    )
    monkeypatch.setattr(
        "stock_platform.auth.deps.to_user_view",
        lambda user, rbac: SimpleNamespace(
            username="admin",
            roles=["admin"],
            permissions=["users:read"],
            display_name=None,
            email=None,
        ),
    )

    principal = require_admin(
        x_admin_api_key=None,
        credentials=HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="token"
        ),
        session=session,
        settings=settings,
    )
    assert isinstance(principal, AuthenticatedUser)
    assert principal.user_id == 7
    assert principal.username == "admin"
    assert principal.is_admin
    session.commit.assert_called()


def test_require_admin_rejects_non_admin_jwt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_api_key", "")
    user = SimpleNamespace(
        user_id=8,
        username="member",
        is_active=True,
        roles=["user"],
    )
    session = _stub_session()

    monkeypatch.setattr(
        "stock_platform.auth.deps.JwtTokenService",
        lambda _settings: SimpleNamespace(
            decode_access_token=lambda token: {"sub": "8"}
        ),
    )
    monkeypatch.setattr(
        "stock_platform.auth.deps.AuthRepository",
        lambda _session: SimpleNamespace(get_by_id=lambda user_id: user),
    )
    monkeypatch.setattr(
        "stock_platform.auth.deps.RbacRepository",
        lambda _session: MagicMock(),
    )
    monkeypatch.setattr(
        "stock_platform.auth.role_sync.reconcile_user_roles",
        lambda session, user, rbac, *, commit=False: (["user"], False),
    )
    monkeypatch.setattr(
        "stock_platform.auth.role_sync.resolve_role_codes",
        lambda user, rbac=None: ["user"],
    )

    with pytest.raises(HTTPException) as exc:
        require_admin(
            x_admin_api_key=None,
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="token"
            ),
            session=session,
            settings=settings,
        )
    assert exc.value.status_code == 403
    assert "관리자" in str(exc.value.detail)
