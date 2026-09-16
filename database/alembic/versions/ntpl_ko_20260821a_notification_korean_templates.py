"""Notification Korean templates + code dictionary + delivery log.

Revision ID: ntpl_ko_20260821a
Revises: p7q8r9s0t1u2
Create Date: 2026-08-21

NOTE: 저장소 Alembic graph에 기존 CycleDetected가 있어 upgrade head가
실패할 수 있다. 이 경우 DDL은 ops에서 본 파일 upgrade()를 수동 적용하고
alembic_version에 ntpl_ko_20260821a 를 stamp한다.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ntpl_ko_20260821a"
down_revision: Union[str, Sequence[str], None] = "p7q8r9s0t1u2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS notification")

    op.add_column(
        "notification",
        sa.Column("rendered_title", sa.String(length=300), nullable=True),
        schema="notification",
    )
    op.add_column(
        "notification",
        sa.Column("rendered_message", sa.Text(), nullable=True),
        schema="notification",
    )
    op.add_column(
        "notification",
        sa.Column(
            "locale",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'ko-KR'"),
        ),
        schema="notification",
    )
    op.add_column(
        "notification",
        sa.Column("template_id", sa.BigInteger(), nullable=True),
        schema="notification",
    )
    op.add_column(
        "notification",
        sa.Column("template_version", sa.Integer(), nullable=True),
        schema="notification",
    )
    op.add_column(
        "notification",
        sa.Column(
            "original_payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="notification",
    )

    op.create_table(
        "message_template",
        sa.Column(
            "message_template_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column(
            "locale",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'ko-KR'"),
        ),
        sa.Column(
            "severity",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'INFO'"),
        ),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column(
            "audience",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'BOTH'"),
        ),
        sa.Column("title_template", sa.String(length=400), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("short_body_template", sa.Text(), nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "variables_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "event_type",
            "channel",
            "locale",
            "version",
            name="uq_message_template_event_channel_locale_ver",
        ),
        schema="notification",
    )
    op.create_index(
        "ix_message_template_lookup",
        "message_template",
        ["event_type", "channel", "locale", "enabled"],
        schema="notification",
    )

    op.create_table(
        "code_translation",
        sa.Column(
            "code_translation_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("code_group", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column(
            "locale",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'ko-KR'"),
        ),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "code_group",
            "code",
            "locale",
            name="uq_code_translation_group_code_locale",
        ),
        schema="notification",
    )

    op.create_table(
        "channel_delivery_log",
        sa.Column(
            "channel_delivery_log_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("recipient", sa.String(length=200), nullable=True),
        sa.Column("rendered_title", sa.String(length=400), nullable=True),
        sa.Column("rendered_message", sa.Text(), nullable=True),
        sa.Column(
            "original_payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("template_id", sa.BigInteger(), nullable=True),
        sa.Column("template_version", sa.Integer(), nullable=True),
        sa.Column("locale", sa.String(length=16), nullable=True),
        sa.Column(
            "missing_variables_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="notification",
    )
    op.create_index(
        "ix_channel_delivery_log_created",
        "channel_delivery_log",
        ["created_at"],
        schema="notification",
    )
    op.create_index(
        "ix_channel_delivery_log_event",
        "channel_delivery_log",
        ["event_type", "channel"],
        schema="notification",
    )


def downgrade() -> None:
    op.drop_table("channel_delivery_log", schema="notification")
    op.drop_table("code_translation", schema="notification")
    op.drop_table("message_template", schema="notification")
    op.drop_column(
        "notification", "original_payload_json", schema="notification"
    )
    op.drop_column("notification", "template_version", schema="notification")
    op.drop_column("notification", "template_id", schema="notification")
    op.drop_column("notification", "locale", schema="notification")
    op.drop_column("notification", "rendered_message", schema="notification")
    op.drop_column("notification", "rendered_title", schema="notification")
