from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from stock_platform.auth.models import AuthUser, RefreshToken

SortField = Literal[
    "user_id",
    "username",
    "display_name",
    "is_active",
    "created_at",
    "updated_at",
]
SortOrder = Literal["asc", "desc"]


class AuthRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _not_deleted(self):
        return AuthUser.deleted_at.is_(None)

    def count_users(self, *, include_deleted: bool = False) -> int:
        stmt = select(func.count()).select_from(AuthUser)
        if not include_deleted:
            stmt = stmt.where(self._not_deleted())
        return int(self._session.scalar(stmt) or 0)

    def get_by_id(
        self,
        user_id: int,
        *,
        include_deleted: bool = False,
    ) -> AuthUser | None:
        user = self._session.get(AuthUser, user_id)
        if user is None:
            return None
        if not include_deleted and user.deleted_at is not None:
            return None
        return user

    def get_by_username(
        self,
        username: str,
        *,
        include_deleted: bool = False,
    ) -> AuthUser | None:
        stmt = select(AuthUser).where(
            AuthUser.username == username.strip().lower()
        )
        if not include_deleted:
            stmt = stmt.where(self._not_deleted())
        return self._session.scalar(stmt)

    def get_by_email(
        self,
        email: str,
        *,
        include_deleted: bool = False,
    ) -> AuthUser | None:
        normalized = email.strip().lower()
        if not normalized:
            return None
        stmt = select(AuthUser).where(AuthUser.email == normalized)
        if not include_deleted:
            stmt = stmt.where(self._not_deleted())
        return self._session.scalar(stmt)

    def get_by_username_or_email(
        self,
        identifier: str,
        *,
        include_deleted: bool = False,
    ) -> AuthUser | None:
        key = identifier.strip().lower()
        if not key:
            return None
        if "@" in key:
            user = self.get_by_email(key, include_deleted=include_deleted)
            if user is not None:
                return user
        return self.get_by_username(key, include_deleted=include_deleted)

    def username_exists(self, username: str) -> bool:
        return self.get_by_username(username) is not None

    def email_exists(self, email: str) -> bool:
        return self.get_by_email(email) is not None

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        display_name: str | None,
        roles: list[str],
        is_active: bool = True,
        email: str | None = None,
        terms_accepted_at: datetime | None = None,
    ) -> AuthUser:
        user = AuthUser(
            username=username.strip().lower(),
            password_hash=password_hash,
            display_name=display_name,
            roles=roles,
            is_active=is_active,
            email=(
                email.strip().lower()
                if email and email.strip()
                else None
            ),
            terms_accepted_at=terms_accepted_at,
        )
        self._session.add(user)
        self._session.flush()
        return user

    def list_users(
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
    ) -> tuple[list[AuthUser], int]:
        filters: list[Any] = []
        if not include_deleted:
            filters.append(self._not_deleted())
        if is_active is not None:
            filters.append(AuthUser.is_active.is_(is_active))
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(
                or_(
                    AuthUser.username.ilike(pattern),
                    AuthUser.display_name.ilike(pattern),
                    AuthUser.email.ilike(pattern),
                )
            )
        if role:
            # JSONB 배열 포함 여부
            filters.append(
                AuthUser.roles.contains([role.strip()])
            )

        count_stmt = select(func.count()).select_from(AuthUser)
        if filters:
            count_stmt = count_stmt.where(and_(*filters))
        total = int(self._session.scalar(count_stmt) or 0)

        sort_column = {
            "user_id": AuthUser.user_id,
            "username": AuthUser.username,
            "display_name": AuthUser.display_name,
            "is_active": AuthUser.is_active,
            "created_at": AuthUser.created_at,
            "updated_at": AuthUser.updated_at,
        }[sort_by]
        order_expr = (
            sort_column.asc()
            if sort_order == "asc"
            else sort_column.desc()
        )

        stmt = select(AuthUser)
        if filters:
            stmt = stmt.where(and_(*filters))
        stmt = (
            stmt.order_by(order_expr, AuthUser.user_id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list(self._session.scalars(stmt))
        return rows, total

    def update_user(
        self,
        user: AuthUser,
        *,
        display_name: str | None = None,
        roles: list[str] | None = None,
        is_active: bool | None = None,
    ) -> AuthUser:
        if display_name is not None:
            user.display_name = display_name
        if roles is not None:
            user.roles = roles
        if is_active is not None:
            user.is_active = is_active
        user.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return user

    def soft_delete(self, user: AuthUser) -> AuthUser:
        now = datetime.now(timezone.utc)
        user.deleted_at = now
        user.is_active = False
        user.updated_at = now
        self._session.flush()
        return user

    def save_refresh_token(
        self,
        *,
        user_id: int,
        jti: str,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        row = RefreshToken(
            user_id=user_id,
            jti=jti,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get_refresh_by_jti(self, jti: str) -> RefreshToken | None:
        return self._session.scalar(
            select(RefreshToken).where(RefreshToken.jti == jti)
        )

    def revoke_refresh(self, jti: str) -> bool:
        row = self.get_refresh_by_jti(jti)
        if row is None:
            return False
        if row.revoked_at is not None:
            return True
        row.revoked_at = datetime.now(timezone.utc)
        self._session.flush()
        return True

    def revoke_all_for_user(self, user_id: int) -> int:
        result = self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        return int(result.rowcount or 0)

    def update_password(
        self,
        user: AuthUser,
        *,
        password_hash: str,
    ) -> AuthUser:
        user.password_hash = password_hash
        user.password_changed_at = datetime.now(timezone.utc)
        user.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return user
