from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stock_platform.database.base import Base


class Role(Base):
    __tablename__ = "role"
    __table_args__ = {"schema": "auth"}

    role_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    permissions: Mapped[list["Permission"]] = relationship(
        secondary="auth.role_permission",
        back_populates="roles",
        lazy="selectin",
        viewonly=False,
    )


class Permission(Base):
    __tablename__ = "permission"
    __table_args__ = {"schema": "auth"}

    permission_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    roles: Mapped[list[Role]] = relationship(
        secondary="auth.role_permission",
        back_populates="permissions",
        lazy="selectin",
    )


class UserRole(Base):
    __tablename__ = "user_role"
    __table_args__ = {"schema": "auth"}

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.user.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.role.role_id", ondelete="CASCADE"),
        primary_key=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class RolePermission(Base):
    __tablename__ = "role_permission"
    __table_args__ = {"schema": "auth"}

    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.role.role_id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.permission.permission_id", ondelete="CASCADE"),
        primary_key=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
