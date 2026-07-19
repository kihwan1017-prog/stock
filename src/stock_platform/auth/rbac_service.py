from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stock_platform.auth.rbac_repository import RbacRepository
from stock_platform.auth.service import AuthError


@dataclass(frozen=True)
class RoleView:
    id: int
    code: str
    name: str
    description: str | None
    is_system: bool
    permissions: list[str]


@dataclass(frozen=True)
class PermissionView:
    id: int
    code: str
    name: str
    category: str
    description: str | None


class RbacService:
    def __init__(self, repository: RbacRepository) -> None:
        self._repository = repository

    def list_roles(self) -> list[RoleView]:
        roles = self._repository.list_roles()
        result: list[RoleView] = []
        for role in roles:
            detailed = self._repository.get_role(role.role_id)
            perms = (
                [p.code for p in detailed.permissions]
                if detailed is not None
                else []
            )
            result.append(
                RoleView(
                    id=role.role_id,
                    code=role.code,
                    name=role.name,
                    description=role.description,
                    is_system=role.is_system,
                    permissions=sorted(perms),
                )
            )
        return result

    def get_role(self, role_id: int) -> RoleView:
        role = self._repository.get_role(role_id)
        if role is None:
            raise AuthError("역할을 찾을 수 없습니다.")
        return RoleView(
            id=role.role_id,
            code=role.code,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            permissions=sorted(p.code for p in role.permissions),
        )

    def list_permissions(
        self,
        *,
        category: str | None = None,
    ) -> list[PermissionView]:
        rows = self._repository.list_permissions(category=category)
        return [
            PermissionView(
                id=row.permission_id,
                code=row.code,
                name=row.name,
                category=row.category,
                description=row.description,
            )
            for row in rows
        ]

    def set_role_permissions(
        self,
        role_id: int,
        *,
        permission_codes: list[str],
    ) -> RoleView:
        role = self._repository.get_role(role_id)
        if role is None:
            raise AuthError("역할을 찾을 수 없습니다.")
        if role.is_system and role.code == "admin":
            # admin은 항상 전체 권한 유지
            all_ids = [
                p.permission_id
                for p in self._repository.list_permissions()
            ]
            self._repository.replace_role_permissions(
                role_id, all_ids
            )
            return self.get_role(role_id)

        ids = self._repository.get_permission_ids_by_codes(
            permission_codes
        )
        if len(ids) != len(set(permission_codes)):
            raise AuthError("존재하지 않는 permission code가 있습니다.")
        self._repository.replace_role_permissions(role_id, ids)
        return self.get_role(role_id)

    def set_user_roles(
        self,
        user_id: int,
        *,
        role_codes: list[str],
    ) -> list[str]:
        if not role_codes:
            raise AuthError("역할이 최소 1개 필요합니다.")
        role_ids = self._repository.get_role_ids_by_codes(role_codes)
        if not role_ids:
            raise AuthError("유효한 역할이 없습니다.")
        self._repository.replace_user_roles(user_id, role_ids)
        return self._repository.list_role_codes_for_user(user_id)

    def permissions_for_user(self, user_id: int) -> list[str]:
        return self._repository.list_permission_codes_for_user(user_id)

    def roles_for_user(self, user_id: int) -> list[str]:
        return self._repository.list_role_codes_for_user(user_id)


def role_view_dict(view: RoleView) -> dict[str, Any]:
    return {
        "id": view.id,
        "code": view.code,
        "name": view.name,
        "description": view.description,
        "is_system": view.is_system,
        "permissions": view.permissions,
    }


def permission_view_dict(view: PermissionView) -> dict[str, Any]:
    return {
        "id": view.id,
        "code": view.code,
        "name": view.name,
        "category": view.category,
        "description": view.description,
    }
