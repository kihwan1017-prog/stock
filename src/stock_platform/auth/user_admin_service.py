from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from stock_platform.auth.models import AuthUser
from stock_platform.auth.password import PasswordHasher
from stock_platform.auth.rbac_repository import RbacRepository
from stock_platform.auth.repository import AuthRepository, SortField, SortOrder
from stock_platform.auth.service import AuthError


ALLOWED_ROLES = frozenset({"admin", "operator", "viewer"})
# STEP2 legacy alias
_ROLE_ALIASES = {"user": "viewer"}


@dataclass(frozen=True)
class MemberView:
    id: str
    username: str
    display_name: str | None
    roles: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    password_changed_at: datetime
    deleted_at: datetime | None
    email: str | None = None


def to_member_view(
    user: AuthUser,
    *,
    roles: list[str] | None = None,
) -> MemberView:
    resolved = roles if roles is not None else [
        str(item) for item in (user.roles or [])
    ]
    return MemberView(
        id=str(user.user_id),
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        roles=resolved,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        password_changed_at=user.password_changed_at,
        deleted_at=user.deleted_at,
    )


def member_view_dict(view: MemberView) -> dict[str, Any]:
    return {
        "id": view.id,
        "username": view.username,
        "email": view.email,
        "display_name": view.display_name,
        "roles": view.roles,
        "is_active": view.is_active,
        "created_at": view.created_at,
        "updated_at": view.updated_at,
        "password_changed_at": view.password_changed_at,
        "deleted_at": view.deleted_at,
    }


class UserAdminService:
    """관리자 회원 CRUD (Soft Delete)."""

    def __init__(
        self,
        repository: AuthRepository,
        rbac_repository: RbacRepository | None = None,
    ) -> None:
        self._repository = repository
        self._rbac = rbac_repository
        self._passwords = PasswordHasher()

    def list_members(
        self,
        *,
        q: str | None = None,
        is_active: bool | None = None,
        role: str | None = None,
        include_deleted: bool = False,
        sort_by: SortField = "created_at",
        sort_order: SortOrder = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MemberView], int]:
        rows, total = self._repository.list_users(
            q=q,
            is_active=is_active,
            role=role,
            include_deleted=include_deleted,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )
        return [self._to_view(row) for row in rows], total

    def get_member(
        self,
        user_id: int,
        *,
        include_deleted: bool = False,
    ) -> MemberView:
        user = self._repository.get_by_id(
            user_id,
            include_deleted=include_deleted,
        )
        if user is None:
            raise AuthError("회원을 찾을 수 없습니다.")
        return self._to_view(user)

    def create_member(
        self,
        *,
        username: str,
        password: str,
        display_name: str | None,
        roles: list[str],
        is_active: bool = True,
        email: str | None = None,
    ) -> MemberView:
        normalized = username.strip().lower()
        if self._repository.get_by_username(
            normalized,
            include_deleted=True,
        ):
            raise AuthError("이미 사용 중인 사용자명입니다.")
        if email and self._repository.email_exists(email):
            raise AuthError("이미 사용 중인 이메일입니다.")
        validated_roles = self._validate_roles(roles)
        user = self._repository.create_user(
            username=normalized,
            password_hash=self._passwords.hash(password),
            display_name=display_name,
            roles=validated_roles,
            is_active=is_active,
            email=email,
        )
        self._sync_roles(user.user_id, validated_roles)
        return self._to_view(user)

    def update_member(
        self,
        user_id: int,
        *,
        display_name: str | None = None,
        email: str | None = None,
        roles: list[str] | None = None,
        is_active: bool | None = None,
        actor_user_id: int | None = None,
    ) -> MemberView:
        user = self._require_active_record(user_id)
        validated_roles = (
            self._validate_roles(roles) if roles is not None else None
        )
        if (
            actor_user_id is not None
            and user.user_id == actor_user_id
            and is_active is False
        ):
            raise AuthError("본인 계정을 비활성화할 수 없습니다.")
        if (
            actor_user_id is not None
            and user.user_id == actor_user_id
            and validated_roles is not None
            and "admin" not in validated_roles
        ):
            raise AuthError("본인 계정의 admin 역할을 제거할 수 없습니다.")
        if email is not None:
            existing = self._repository.get_by_email(email)
            if existing is not None and existing.user_id != user_id:
                raise AuthError("이미 사용 중인 이메일입니다.")
            user.email = email

        updated = self._repository.update_user(
            user,
            display_name=display_name,
            roles=validated_roles,
            is_active=is_active,
        )
        if validated_roles is not None:
            self._sync_roles(user_id, validated_roles)
        if is_active is False:
            self._repository.revoke_all_for_user(user_id)
        return self._to_view(updated)

    def set_active(
        self,
        user_id: int,
        *,
        is_active: bool,
        actor_user_id: int | None = None,
    ) -> MemberView:
        return self.update_member(
            user_id,
            is_active=is_active,
            actor_user_id=actor_user_id,
        )

    def soft_delete_member(
        self,
        user_id: int,
        *,
        actor_user_id: int | None = None,
    ) -> MemberView:
        user = self._require_active_record(user_id)
        if actor_user_id is not None and user.user_id == actor_user_id:
            raise AuthError("본인 계정을 삭제할 수 없습니다.")
        deleted = self._repository.soft_delete(user)
        self._repository.revoke_all_for_user(user_id)
        return self._to_view(deleted)

    def reset_password(
        self,
        user_id: int,
        *,
        new_password: str | None = None,
    ) -> tuple[MemberView, str]:
        """비밀번호 초기화. new_password 없으면 임시 비밀번호 생성."""

        user = self._require_active_record(user_id)
        temporary = new_password or self._generate_temporary_password()
        self._repository.update_password(
            user,
            password_hash=self._passwords.hash(temporary),
        )
        self._repository.revoke_all_for_user(user_id)
        refreshed = self._repository.get_by_id(user_id)
        assert refreshed is not None
        return self._to_view(refreshed), temporary

    def _require_active_record(self, user_id: int) -> AuthUser:
        user = self._repository.get_by_id(user_id)
        if user is None:
            raise AuthError("회원을 찾을 수 없습니다.")
        return user

    def _to_view(self, user: AuthUser) -> MemberView:
        roles = None
        if self._rbac is not None:
            codes = self._rbac.list_role_codes_for_user(user.user_id)
            if codes:
                roles = codes
        return to_member_view(user, roles=roles)

    def _sync_roles(self, user_id: int, role_codes: list[str]) -> None:
        if self._rbac is None:
            return
        role_ids = self._rbac.get_role_ids_by_codes(role_codes)
        if not role_ids:
            raise AuthError("유효한 역할이 없습니다.")
        self._rbac.replace_user_roles(user_id, role_ids)

    @staticmethod
    def _validate_roles(roles: list[str]) -> list[str]:
        if not roles:
            raise AuthError("역할이 최소 1개 필요합니다.")
        cleaned = [
            _ROLE_ALIASES.get(
                str(role).strip().lower(),
                str(role).strip().lower(),
            )
            for role in roles
        ]
        invalid = [role for role in cleaned if role not in ALLOWED_ROLES]
        if invalid:
            raise AuthError(
                f"허용되지 않는 역할입니다: {', '.join(invalid)}"
            )
        # 중복 제거, 순서 유지
        unique: list[str] = []
        for role in cleaned:
            if role not in unique:
                unique.append(role)
        return unique

    @staticmethod
    def _generate_temporary_password() -> str:
        # 8자 이상 정책 충족
        return f"Tmp!{secrets.token_urlsafe(9)}"
