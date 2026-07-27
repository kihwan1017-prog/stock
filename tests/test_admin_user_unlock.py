"""관리자 unlock / force-logout / member accounts 단위 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.auth.service import AuthError
from stock_platform.auth.user_admin_service import UserAdminService
from stock_platform.auth.user_status import STATUS_LOCKED, resolve_user_status


def test_unlock_member_clears_lock() -> None:
    user = SimpleNamespace(
        user_id=7,
        username="locked",
        email=None,
        display_name="L",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        password_changed_at=datetime.now(timezone.utc),
        deleted_at=None,
        password_change_required=False,
        failed_login_count=5,
        locked_until=datetime.now(timezone.utc) + timedelta(minutes=10),
        last_login_at=None,
        last_login_ip=None,
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    assert resolve_user_status(user) == STATUS_LOCKED

    repo = MagicMock()
    repo.get_by_id.return_value = user

    def _clear_lockout(target):
        target.locked_until = None
        target.failed_login_count = 0
        return target

    repo.clear_lockout.side_effect = _clear_lockout
    service = UserAdminService(repo, rbac_repository=None)
    view = service.unlock_member(7)
    assert user.locked_until is None
    assert user.failed_login_count == 0
    assert view.user_status != STATUS_LOCKED
    repo.clear_lockout.assert_called_once_with(user)


def test_force_logout_member() -> None:
    user = SimpleNamespace(user_id=3, username="u")
    repo = MagicMock()
    repo.get_by_id.return_value = user
    repo.revoke_all_for_user.return_value = 2
    service = UserAdminService(repo)
    result = service.force_logout_member(3)
    assert result["revoked_sessions"] == 2
    repo.revoke_all_for_user.assert_called_once()


def test_force_logout_missing_user() -> None:
    repo = MagicMock()
    repo.get_by_id.return_value = None
    service = UserAdminService(repo)
    with pytest.raises(AuthError):
        service.force_logout_member(99)
