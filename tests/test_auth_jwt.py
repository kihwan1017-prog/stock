from __future__ import annotations

from datetime import timedelta

import pytest

from stock_platform.auth.jwt_service import JwtError, JwtTokenService
from stock_platform.auth.password import PasswordHasher
from stock_platform.common.settings import Settings


def _settings(**overrides) -> Settings:
    base = {
        "db_host": "localhost",
        "db_name": "stock_platform",
        "db_user": "stock_app",
        "db_password": "test",
        "jwt_secret": "unit-test-jwt-secret-key-32chars!!",
        "jwt_access_token_expire_minutes": 15,
        "jwt_refresh_token_expire_days": 7,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.mark.unit
def test_password_hash_and_verify() -> None:
    hashed = PasswordHasher.hash("SecurePass1!")
    assert hashed != "SecurePass1!"
    assert PasswordHasher.verify("SecurePass1!", hashed)
    assert not PasswordHasher.verify("wrong", hashed)


@pytest.mark.unit
def test_password_min_length() -> None:
    with pytest.raises(ValueError):
        PasswordHasher.hash("short")


@pytest.mark.unit
def test_jwt_access_and_refresh_roundtrip() -> None:
    svc = JwtTokenService(_settings())
    access, expires_in = svc.create_access_token(
        user_id=1,
        username="admin",
        roles=["admin"],
    )
    assert expires_in == 15 * 60
    payload = svc.decode_access_token(access)
    assert payload["sub"] == "1"
    assert payload["username"] == "admin"
    assert payload["roles"] == ["admin"]
    assert payload["type"] == "access"

    refresh, jti, expires_at = svc.create_refresh_token(user_id=1)
    refresh_payload = svc.decode_refresh_token(refresh)
    assert refresh_payload["jti"] == jti
    assert refresh_payload["type"] == "refresh"
    assert expires_at is not None


@pytest.mark.unit
def test_jwt_rejects_wrong_type() -> None:
    svc = JwtTokenService(_settings())
    refresh, _, _ = svc.create_refresh_token(user_id=1)
    with pytest.raises(JwtError):
        svc.decode_access_token(refresh)


@pytest.mark.unit
def test_jwt_secret_required() -> None:
    with pytest.raises(JwtError) as exc:
        JwtTokenService(_settings(jwt_secret=""))
    assert "JWT_SECRET 환경변수가 없습니다" in str(exc.value)


@pytest.mark.unit
def test_token_hash_stable() -> None:
    assert JwtTokenService.hash_token("abc") == JwtTokenService.hash_token(
        "abc"
    )
    assert JwtTokenService.hash_token("abc") != JwtTokenService.hash_token(
        "abd"
    )


@pytest.mark.unit
def test_auth_service_login_with_fake_repo() -> None:
    from stock_platform.auth.models import AuthUser
    from stock_platform.auth.service import AuthError, AuthService

    class FakeRepo:
        def __init__(self) -> None:
            self.user = AuthUser(
                user_id=1,
                username="admin",
                password_hash=PasswordHasher.hash("SecurePass1!"),
                display_name="Admin",
                roles=["admin"],
                is_active=True,
            )
            self.tokens: dict[str, object] = {}

        def count_users(self) -> int:
            return 1

        def get_by_username(self, username: str):
            if username.lower() == "admin":
                return self.user
            return None

        def get_by_username_or_email(self, identifier: str):
            return self.get_by_username(identifier)

        def get_by_id(self, user_id: int):
            return self.user if user_id == 1 else None

        def save_refresh_token(self, **kwargs):
            self.tokens[kwargs["jti"]] = kwargs
            return kwargs

        def get_refresh_by_jti(self, jti: str):
            return None

        def revoke_refresh(self, jti: str) -> bool:
            return True

        def revoke_all_for_user(self, user_id: int) -> int:
            return 0

        def create_user(self, **kwargs):
            raise NotImplementedError

        def update_password(self, user, *, password_hash: str):
            user.password_hash = password_hash
            return user

    service = AuthService(
        repository=FakeRepo(),  # type: ignore[arg-type]
        settings=_settings(),
    )
    pair, view = service.login(
        username="admin",
        password="SecurePass1!",
    )
    assert pair.access_token
    assert pair.refresh_token
    assert view.username == "admin"
    assert "admin" in view.roles

    with pytest.raises(AuthError):
        service.login(username="admin", password="wrong-password")
