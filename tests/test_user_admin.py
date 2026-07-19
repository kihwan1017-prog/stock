from __future__ import annotations

from datetime import datetime, timezone

import pytest

from stock_platform.auth.models import AuthUser
from stock_platform.auth.password import PasswordHasher
from stock_platform.auth.service import AuthError
from stock_platform.auth.user_admin_service import UserAdminService


class _FakeRepo:
    def __init__(self) -> None:
        self.users: dict[int, AuthUser] = {}
        self._seq = 0

    def count_users(self, *, include_deleted: bool = False) -> int:
        return len(
            [
                u
                for u in self.users.values()
                if include_deleted or u.deleted_at is None
            ]
        )

    def get_by_id(self, user_id: int, *, include_deleted: bool = False):
        user = self.users.get(user_id)
        if user is None:
            return None
        if not include_deleted and user.deleted_at is not None:
            return None
        return user

    def get_by_username(self, username: str, *, include_deleted: bool = False):
        for user in self.users.values():
            if user.username == username.strip().lower():
                if not include_deleted and user.deleted_at is not None:
                    return None
                return user
        return None

    def create_user(self, **kwargs):
        self._seq += 1
        now = datetime.now(timezone.utc)
        user = AuthUser(
            user_id=self._seq,
            username=kwargs["username"],
            password_hash=kwargs["password_hash"],
            display_name=kwargs.get("display_name"),
            roles=kwargs.get("roles") or ["user"],
            is_active=kwargs.get("is_active", True),
            created_at=now,
            updated_at=now,
            password_changed_at=now,
            deleted_at=None,
        )
        self.users[user.user_id] = user
        return user

    def list_users(self, **kwargs):
        include_deleted = kwargs.get("include_deleted", False)
        q = (kwargs.get("q") or "").lower()
        is_active = kwargs.get("is_active")
        role = kwargs.get("role")
        rows = []
        for user in self.users.values():
            if not include_deleted and user.deleted_at is not None:
                continue
            if is_active is not None and user.is_active is not is_active:
                continue
            if role and role not in (user.roles or []):
                continue
            if q and q not in user.username and q not in (
                user.display_name or ""
            ).lower():
                continue
            rows.append(user)
        sort_by = kwargs.get("sort_by", "created_at")
        sort_order = kwargs.get("sort_order", "desc")
        reverse = sort_order == "desc"
        rows.sort(
            key=lambda u: getattr(u, sort_by) or "",
            reverse=reverse,
        )
        limit = kwargs.get("limit", 20)
        offset = kwargs.get("offset", 0)
        return rows[offset : offset + limit], len(rows)

    def update_user(self, user, **kwargs):
        if kwargs.get("display_name") is not None:
            user.display_name = kwargs["display_name"]
        if kwargs.get("roles") is not None:
            user.roles = kwargs["roles"]
        if kwargs.get("is_active") is not None:
            user.is_active = kwargs["is_active"]
        user.updated_at = datetime.now(timezone.utc)
        return user

    def soft_delete(self, user):
        user.deleted_at = datetime.now(timezone.utc)
        user.is_active = False
        return user

    def update_password(self, user, *, password_hash: str):
        user.password_hash = password_hash
        user.password_changed_at = datetime.now(timezone.utc)
        return user

    def revoke_all_for_user(self, user_id: int) -> int:
        return 1


@pytest.mark.unit
def test_user_admin_create_list_update_soft_delete() -> None:
    repo = _FakeRepo()
    service = UserAdminService(repo)  # type: ignore[arg-type]

    created = service.create_member(
        username="trader1",
        password="SecurePass1!",
        display_name="Trader",
        roles=["user"],
    )
    assert created.username == "trader1"
    assert created.is_active is True

    items, total = service.list_members(q="trad")
    assert total == 1
    assert items[0].id == created.id

    updated = service.update_member(
        int(created.id),
        display_name="Trader One",
        roles=["user", "admin"],
    )
    assert updated.display_name == "Trader One"
    assert "admin" in updated.roles

    deactivated = service.set_active(int(created.id), is_active=False)
    assert deactivated.is_active is False

    deleted = service.soft_delete_member(int(created.id))
    assert deleted.deleted_at is not None
    items_after, total_after = service.list_members()
    assert total_after == 0
    assert items_after == []


@pytest.mark.unit
def test_user_admin_cannot_delete_self() -> None:
    repo = _FakeRepo()
    service = UserAdminService(repo)  # type: ignore[arg-type]
    admin = service.create_member(
        username="admin2",
        password="SecurePass1!",
        display_name="Admin",
        roles=["admin"],
    )
    with pytest.raises(AuthError):
        service.soft_delete_member(
            int(admin.id),
            actor_user_id=int(admin.id),
        )


@pytest.mark.unit
def test_user_admin_reset_password() -> None:
    repo = _FakeRepo()
    service = UserAdminService(repo)  # type: ignore[arg-type]
    user = service.create_member(
        username="resetme",
        password="SecurePass1!",
        display_name=None,
        roles=["user"],
    )
    view, temporary = service.reset_password(int(user.id))
    assert len(temporary) >= 8
    assert PasswordHasher.verify(
        temporary,
        repo.users[int(view.id)].password_hash,
    )


@pytest.mark.unit
def test_user_admin_duplicate_username() -> None:
    repo = _FakeRepo()
    service = UserAdminService(repo)  # type: ignore[arg-type]
    service.create_member(
        username="dup",
        password="SecurePass1!",
        display_name=None,
        roles=["user"],
    )
    with pytest.raises(AuthError):
        service.create_member(
            username="dup",
            password="SecurePass1!",
            display_name=None,
            roles=["user"],
        )
