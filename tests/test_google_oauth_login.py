"""Google OAuth V1 — DB mapping / security unit tests (no live Google)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.auth.google_oauth import (
    GoogleIdentity,
    GoogleOAuthService,
    upsert_google_identity,
)
from stock_platform.auth.models import AuthUser, OAuthHandoff, UserExternalIdentity
from stock_platform.auth.service import AuthError, AuthService


class _FakeRepo:
    def __init__(self, session, user: AuthUser | None = None) -> None:
        self._session = session
        self._user = user

    def get_by_id(self, user_id: int, **kwargs):
        if self._user and int(self._user.user_id) == int(user_id):
            return self._user
        return None

    def get_by_email(self, email: str, **kwargs):
        if self._user and (self._user.email or "").lower() == email.lower():
            return self._user
        return None

    def mark_last_login(self, user: AuthUser) -> None:
        user.last_login_at = datetime.now(timezone.utc)


def _make_user(**overrides) -> AuthUser:
    user = AuthUser(
        username=overrides.get("username", "admin"),
        email=overrides.get("email", "admin@example.com"),
        password_hash=overrides.get("password_hash", "x" * 60),
        roles=overrides.get("roles", ["admin"]),
        is_active=overrides.get("is_active", True),
        email_verified=overrides.get("email_verified", False),
        failed_login_count=0,
    )
    user.user_id = overrides.get("user_id", 7)
    user.deleted_at = overrides.get("deleted_at")
    user.locked_until = overrides.get("locked_until")
    return user


def _settings():
    return SimpleNamespace(
        jwt_secret="test-secret-for-google-oauth-unit",
        jwt_algorithm="HS256",
        jwt_access_token_expire_minutes=30,
        jwt_refresh_token_expire_days=7,
    )


def _svc(repo) -> AuthService:
    return AuthService(repo, settings=_settings(), jwt_service=MagicMock())


def test_resolve_google_requires_email_verified(monkeypatch):
    session = MagicMock()
    session.scalar.return_value = None
    user = _make_user()
    svc = _svc(_FakeRepo(session, user))
    monkeypatch.setattr(svc, "_rbac", None)

    with pytest.raises(AuthError, match="인증되지 않은"):
        svc.resolve_google_user(
            subject="sub-1",
            email="admin@example.com",
            email_verified=False,
        )


def test_resolve_google_unknown_email(monkeypatch):
    session = MagicMock()
    session.scalar.return_value = None
    svc = _svc(_FakeRepo(session, None))
    monkeypatch.setattr(svc, "_rbac", None)

    with pytest.raises(AuthError, match="GOOGLE_ACCOUNT_NOT_REGISTERED"):
        svc.resolve_google_user(
            subject="sub-1",
            email="nobody@example.com",
            email_verified=True,
        )


def test_resolve_google_inactive_user(monkeypatch):
    session = MagicMock()
    session.scalar.return_value = None
    user = _make_user(is_active=False)
    svc = _svc(_FakeRepo(session, user))
    monkeypatch.setattr(svc, "_rbac", None)

    with pytest.raises(AuthError, match="비활성"):
        svc.resolve_google_user(
            subject="sub-1",
            email="admin@example.com",
            email_verified=True,
        )


def test_resolve_google_maps_existing_email(monkeypatch):
    session = MagicMock()
    session.scalar.return_value = None
    user = _make_user(email_verified=False)
    svc = _svc(_FakeRepo(session, user))
    monkeypatch.setattr(svc, "_rbac", None)

    def _upsert(sess, *, user_id, subject, email):
        return UserExternalIdentity(
            user_id=user_id,
            provider="google",
            provider_subject=subject,
            email_snapshot=email,
        )

    monkeypatch.setattr(
        "stock_platform.auth.google_oauth.upsert_google_identity",
        _upsert,
    )

    resolved = svc.resolve_google_user(
        subject="google-sub-9",
        email="admin@example.com",
        email_verified=True,
    )
    assert resolved.user_id == 7
    assert resolved.email_verified is True


def test_upsert_google_identity_conflict():
    session = MagicMock()
    existing = UserExternalIdentity(
        user_id=1,
        provider="google",
        provider_subject="sub-a",
        email_snapshot="a@example.com",
    )
    session.scalar.return_value = existing
    with pytest.raises(AuthError, match="다른 사용자"):
        upsert_google_identity(
            session, user_id=2, subject="sub-a", email="b@example.com"
        )


def test_exchange_handoff_expired():
    session = MagicMock()
    row = OAuthHandoff(
        code="code-1234567890123456",
        user_id=7,
        next_path=None,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        used_at=None,
    )
    session.get.return_value = row
    settings = SimpleNamespace(
        google_oauth_enabled=True,
        google_oauth_client_id="cid",
        google_oauth_client_secret="sec",
        google_oauth_redirect_uri="https://example/callback",
        google_oauth_frontend_complete_url="https://example/complete",
    )
    auth = MagicMock()
    oauth = GoogleOAuthService(session, settings, auth)
    with pytest.raises(AuthError, match="만료"):
        oauth.exchange_handoff(code="code-1234567890123456")


def test_verify_id_token_rejects_bad_nonce(monkeypatch):
    settings = SimpleNamespace(
        google_oauth_enabled=True,
        google_oauth_client_id="cid",
        google_oauth_client_secret="sec",
        google_oauth_redirect_uri="https://example/callback",
        google_oauth_frontend_complete_url="https://example/complete",
    )
    oauth = GoogleOAuthService(MagicMock(), settings, MagicMock())

    class _Key:
        key = "k"

    monkeypatch.setattr(
        oauth._jwks,
        "get_signing_key_from_jwt",
        lambda _t: _Key(),
    )

    import jwt as pyjwt

    monkeypatch.setattr(
        pyjwt,
        "decode",
        lambda *a, **k: {
            "sub": "s",
            "email": "a@b.com",
            "email_verified": True,
            "nonce": "wrong",
        },
    )

    with pytest.raises(AuthError, match="nonce"):
        oauth._verify_id_token("token", expected_nonce="expected")


def test_google_identity_dataclass():
    ident = GoogleIdentity(
        subject="x", email="a@b.com", email_verified=True
    )
    assert ident.email_verified is True
