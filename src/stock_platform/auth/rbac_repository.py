from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from stock_platform.auth.rbac_models import (
    Permission,
    Role,
    RolePermission,
    UserRole,
)


class RbacRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_roles(self) -> list[Role]:
        return list(
            self._session.scalars(
                select(Role).order_by(Role.role_id.asc())
            )
        )

    def get_role_by_code(self, code: str) -> Role | None:
        return self._session.scalar(
            select(Role).where(Role.code == code.strip().lower())
        )

    def get_role(self, role_id: int) -> Role | None:
        return self._session.scalar(
            select(Role)
            .where(Role.role_id == role_id)
            .options(selectinload(Role.permissions))
        )

    def list_permissions(
        self,
        *,
        category: str | None = None,
    ) -> list[Permission]:
        stmt = select(Permission).order_by(
            Permission.category.asc(),
            Permission.code.asc(),
        )
        if category:
            stmt = stmt.where(Permission.category == category)
        return list(self._session.scalars(stmt))

    def get_permission_ids_by_codes(
        self,
        codes: list[str],
    ) -> list[int]:
        if not codes:
            return []
        rows = self._session.scalars(
            select(Permission.permission_id).where(
                Permission.code.in_(codes)
            )
        )
        return list(rows)

    def get_role_ids_by_codes(self, codes: list[str]) -> list[int]:
        if not codes:
            return []
        normalized = [c.strip().lower() for c in codes]
        # legacy alias
        normalized = [
            "viewer" if code == "user" else code for code in normalized
        ]
        rows = self._session.scalars(
            select(Role.role_id).where(Role.code.in_(normalized))
        )
        return list(rows)

    def list_role_codes_for_user(self, user_id: int) -> list[str]:
        rows = self._session.execute(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.role_id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.code.asc())
        )
        return [str(row[0]) for row in rows]

    def list_permission_codes_for_user(
        self,
        user_id: int,
    ) -> list[str]:
        rows = self._session.execute(
            select(Permission.code)
            .join(
                RolePermission,
                RolePermission.permission_id
                == Permission.permission_id,
            )
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
            .order_by(Permission.code.asc())
            .distinct()
        )
        return [str(row[0]) for row in rows]

    def replace_user_roles(
        self,
        user_id: int,
        role_ids: list[int],
    ) -> None:
        self._session.execute(
            delete(UserRole).where(UserRole.user_id == user_id)
        )
        for role_id in role_ids:
            self._session.add(
                UserRole(user_id=user_id, role_id=role_id)
            )
        self._session.flush()

    def replace_role_permissions(
        self,
        role_id: int,
        permission_ids: list[int],
    ) -> None:
        self._session.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id
            )
        )
        for permission_id in permission_ids:
            self._session.add(
                RolePermission(
                    role_id=role_id,
                    permission_id=permission_id,
                )
            )
        self._session.flush()

    def ensure_user_has_role_code(
        self,
        user_id: int,
        role_code: str,
    ) -> None:
        role = self.get_role_by_code(role_code)
        if role is None:
            return
        existing = self._session.get(
            UserRole, {"user_id": user_id, "role_id": role.role_id}
        )
        if existing is None:
            self._session.add(
                UserRole(user_id=user_id, role_id=role.role_id)
            )
            self._session.flush()
