"""STEP4 — AuthRepository 공개 계약 (Fake와 실구현 동일 시그니처)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from stock_platform.auth.repository import AuthRepository


@pytest.mark.unit
def test_auth_repository_public_contract_methods_exist() -> None:
    """서비스가 의존하는 공개 메서드가 Repository에 존재해야 한다."""

    required = [
        "flush",
        "get_session",
        "get_by_id",
        "get_by_username",
        "get_by_username_or_email",
        "mark_last_login",
        "record_failed_login",
        "revoke_refresh",
        "revoke_all_for_user",
        "set_password_change_required",
        "mark_onboarding_completed",
        "clear_lockout",
        "update_password",
        "save_refresh_token",
    ]
    for name in required:
        assert hasattr(AuthRepository, name), name
        assert callable(getattr(AuthRepository, name))


@pytest.mark.unit
def test_auth_repository_flush_and_get_session() -> None:
    session = SimpleNamespace(flush=lambda: setattr(session, "flushed", True))
    session.flushed = False
    repo = AuthRepository(session)  # type: ignore[arg-type]
    assert repo.get_session() is session
    repo.flush()
    assert session.flushed is True


@pytest.mark.unit
def test_auth_repository_clear_lockout_and_onboarding() -> None:
    calls: list[str] = []
    session = SimpleNamespace(flush=lambda: calls.append("flush"))
    repo = AuthRepository(session)  # type: ignore[arg-type]
    user = SimpleNamespace(
        locked_until=datetime.now(timezone.utc),
        failed_login_count=3,
        updated_at=None,
        onboarding_completed_at=None,
        password_change_required=False,
    )
    repo.clear_lockout(user)  # type: ignore[arg-type]
    assert user.locked_until is None
    assert user.failed_login_count == 0
    assert "flush" in calls

    repo.mark_onboarding_completed(user)  # type: ignore[arg-type]
    assert user.onboarding_completed_at is not None

    repo.set_password_change_required(user, required=True)  # type: ignore[arg-type]
    assert user.password_change_required is True


@pytest.mark.unit
def test_auth_repository_record_failed_login_locks() -> None:
    session = SimpleNamespace(flush=lambda: None)
    repo = AuthRepository(session)  # type: ignore[arg-type]
    user = SimpleNamespace(
        failed_login_count=4,
        locked_until=None,
        updated_at=None,
    )
    repo.record_failed_login(
        user,  # type: ignore[arg-type]
        max_fails=5,
        lockout_minutes=15,
    )
    assert user.failed_login_count == 0
    assert user.locked_until is not None
