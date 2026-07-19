from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from stock_platform.auth.models import AuthUser
from stock_platform.auth.password import PasswordHasher
from stock_platform.auth.service import AuthError, AuthService
from stock_platform.common.settings import Settings


def _settings(**overrides) -> Settings:
    base = {
        "db_host": "localhost",
        "db_name": "stock_platform",
        "db_user": "stock_app",
        "db_password": "test",
        "jwt_secret": "unit-test-jwt-secret-key-32chars!!",
        "app_env": "local",
        "jwt_dev_auto_secret": True,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


class FakeRepo:
    def __init__(self) -> None:
        self.users: dict[str, AuthUser] = {}
        self.by_id: dict[int, AuthUser] = {}
        self.next_id = 1
        self.tokens: dict[str, object] = {}

    def count_users(self) -> int:
        return len(self.users)

    def get_by_username(self, username: str, *, include_deleted: bool = False):
        return self.users.get(username.strip().lower())

    def get_by_email(self, email: str, *, include_deleted: bool = False):
        key = email.strip().lower()
        for user in self.users.values():
            if (user.email or "").lower() == key:
                return user
        return None

    def get_by_username_or_email(self, identifier: str, *, include_deleted: bool = False):
        key = identifier.strip().lower()
        if "@" in key:
            found = self.get_by_email(key)
            if found:
                return found
        return self.get_by_username(key)

    def username_exists(self, username: str) -> bool:
        return self.get_by_username(username) is not None

    def email_exists(self, email: str) -> bool:
        return self.get_by_email(email) is not None

    def get_by_id(self, user_id: int, *, include_deleted: bool = False):
        return self.by_id.get(user_id)

    def create_user(self, **kwargs):
        user = AuthUser(
            user_id=self.next_id,
            username=kwargs["username"],
            password_hash=kwargs["password_hash"],
            display_name=kwargs.get("display_name"),
            roles=kwargs.get("roles") or ["viewer"],
            is_active=kwargs.get("is_active", True),
            email=kwargs.get("email"),
            terms_accepted_at=kwargs.get("terms_accepted_at"),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            password_changed_at=datetime.now(timezone.utc),
        )
        self.next_id += 1
        self.users[user.username] = user
        self.by_id[user.user_id] = user
        return user

    def save_refresh_token(self, **kwargs):
        self.tokens[kwargs["jti"]] = kwargs
        return kwargs

    def get_refresh_by_jti(self, jti: str):
        return None

    def revoke_refresh(self, jti: str) -> bool:
        return True

    def revoke_all_for_user(self, user_id: int) -> int:
        return 0

    def update_password(self, user, *, password_hash: str):
        user.password_hash = password_hash
        return user


@pytest.mark.unit
def test_signup_and_login_by_email() -> None:
    repo = FakeRepo()
    service = AuthService(repository=repo, settings=_settings())  # type: ignore[arg-type]

    pair, view = service.signup(
        name="홍길동",
        username="hong",
        email="hong@example.com",
        password="SecurePass1!",
        password_confirm="SecurePass1!",
        terms_accepted=True,
    )
    assert pair.access_token
    assert pair.refresh_token
    assert view.username == "hong"
    assert view.email == "hong@example.com"
    assert "viewer" in view.roles

    pair2, view2 = service.login(
        username="hong@example.com",
        password="SecurePass1!",
    )
    assert view2.username == "hong"
    assert pair2.access_token


@pytest.mark.unit
def test_signup_rejects_duplicate_username() -> None:
    repo = FakeRepo()
    service = AuthService(repository=repo, settings=_settings())  # type: ignore[arg-type]
    service.signup(
        name="A",
        username="dupuser",
        email="a@example.com",
        password="SecurePass1!",
        password_confirm="SecurePass1!",
        terms_accepted=True,
    )
    with pytest.raises(AuthError, match="아이디"):
        service.signup(
            name="B",
            username="dupuser",
            email="b@example.com",
            password="SecurePass1!",
            password_confirm="SecurePass1!",
            terms_accepted=True,
        )


@pytest.mark.unit
def test_signup_rejects_terms_false() -> None:
    service = AuthService(repository=FakeRepo(), settings=_settings())  # type: ignore[arg-type]
    with pytest.raises(AuthError, match="약관"):
        service.signup(
            name="A",
            username="user1",
            email="a@example.com",
            password="SecurePass1!",
            password_confirm="SecurePass1!",
            terms_accepted=False,
        )


@pytest.mark.unit
def test_signup_rejects_password_mismatch() -> None:
    service = AuthService(repository=FakeRepo(), settings=_settings())  # type: ignore[arg-type]
    with pytest.raises(AuthError, match="비밀번호"):
        service.signup(
            name="A",
            username="user1",
            email="a@example.com",
            password="SecurePass1!",
            password_confirm="OtherPass1!",
            terms_accepted=True,
        )


@pytest.mark.unit
def test_logout_revokes_refresh() -> None:
    repo = FakeRepo()
    service = AuthService(repository=repo, settings=_settings())  # type: ignore[arg-type]
    pair, _ = service.signup(
        name="A",
        username="user1",
        email="a@example.com",
        password="SecurePass1!",
        password_confirm="SecurePass1!",
        terms_accepted=True,
    )
    # logout should not raise even if revoke finds nothing after decode
    service.logout(refresh_token=pair.refresh_token)


@pytest.mark.unit
def test_check_availability() -> None:
    repo = FakeRepo()
    service = AuthService(repository=repo, settings=_settings())  # type: ignore[arg-type]
    assert service.check_username_available("freshuser") is True
    service.signup(
        name="A",
        username="freshuser",
        email="fresh@example.com",
        password="SecurePass1!",
        password_confirm="SecurePass1!",
        terms_accepted=True,
    )
    assert service.check_username_available("freshuser") is False
    assert service.check_email_available("fresh@example.com") is False
    assert service.check_email_available("other@example.com") is True
