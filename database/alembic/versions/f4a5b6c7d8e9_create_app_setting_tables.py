"""create operation app_setting and history

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-07-19 17:40:00.000000

STEP5: DB 기반 Settings + 변경 이력 + settings RBAC permission
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_PERMISSIONS = [
    ("settings:read", "설정 조회", "api"),
    ("settings:write", "설정 변경", "api"),
]


def upgrade() -> None:
    op.create_table(
        "app_setting",
        sa.Column(
            "setting_key",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("value_text", sa.Text(), nullable=False),
        sa.Column(
            "value_type",
            sa.String(length=16),
            nullable=False,
            server_default="string",
        ),
        sa.Column(
            "is_secret",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "description",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.PrimaryKeyConstraint(
            "setting_key",
            name=op.f("pk_app_setting"),
        ),
        schema="operation",
    )
    op.create_index(
        "ix_app_setting_category",
        "app_setting",
        ["category"],
        schema="operation",
    )

    op.create_table(
        "app_setting_history",
        sa.Column(
            "history_id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column(
            "setting_key",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column(
            "actor",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "change_reason",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "history_id",
            name=op.f("pk_app_setting_history"),
        ),
        schema="operation",
    )
    op.create_index(
        "ix_app_setting_history_key_created",
        "app_setting_history",
        ["setting_key", "created_at"],
        schema="operation",
    )

    # RBAC: settings permissions (admin만 — 전체 권한 보유)
    bind = op.get_bind()
    for code, name, category in NEW_PERMISSIONS:
        bind.execute(
            sa.text(
                """
                INSERT INTO auth.permission
                    (code, name, category, description)
                VALUES (:code, :name, :category, :name)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {
                "code": code,
                "name": name,
                "category": category,
            },
        )

    # admin role에 신규 permission 연결
    bind.execute(
        sa.text(
            """
            INSERT INTO auth.role_permission (role_id, permission_id)
            SELECT r.role_id, p.permission_id
            FROM auth.role r
            CROSS JOIN auth.permission p
            WHERE r.code = 'admin'
              AND p.code IN ('settings:read', 'settings:write')
            ON CONFLICT DO NOTHING
            """
        )
    )
    # operator: settings read only
    bind.execute(
        sa.text(
            """
            INSERT INTO auth.role_permission (role_id, permission_id)
            SELECT r.role_id, p.permission_id
            FROM auth.role r
            CROSS JOIN auth.permission p
            WHERE r.code = 'operator'
              AND p.code = 'settings:read'
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            DELETE FROM auth.role_permission
            WHERE permission_id IN (
                SELECT permission_id FROM auth.permission
                WHERE code IN ('settings:read', 'settings:write')
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM auth.permission
            WHERE code IN ('settings:read', 'settings:write')
            """
        )
    )
    op.drop_index(
        "ix_app_setting_history_key_created",
        table_name="app_setting_history",
        schema="operation",
    )
    op.drop_table("app_setting_history", schema="operation")
    op.drop_index(
        "ix_app_setting_category",
        table_name="app_setting",
        schema="operation",
    )
    op.drop_table("app_setting", schema="operation")
