"""STEP69 — user_disclosure_state + disclosure_ai_summary

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_dart_disclosure_stock_receipt",
        "dart_disclosure",
        ["stock_code", "receipt_date"],
        schema="disclosure",
    )
    op.create_index(
        "ix_dart_disclosure_corp_receipt",
        "dart_disclosure",
        ["corp_code", "receipt_date"],
        schema="disclosure",
    )
    op.create_index(
        "ix_dart_disclosure_category_receipt",
        "dart_disclosure",
        ["category_code", "receipt_date"],
        schema="disclosure",
    )

    op.create_table(
        "user_disclosure_state",
        sa.Column(
            "user_disclosure_state_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("disclosure_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_bookmarked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "bookmarked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.user.user_id"],
            name="fk_user_disclosure_state_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["disclosure_id"],
            ["disclosure.dart_disclosure.disclosure_id"],
            name="fk_user_disclosure_state_disclosure",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "disclosure_id",
            name="uq_user_disclosure_state_user_disclosure",
        ),
        schema="disclosure",
    )
    op.create_index(
        "ix_user_disclosure_state_user_read",
        "user_disclosure_state",
        ["user_id", "is_read"],
        schema="disclosure",
    )
    op.create_index(
        "ix_user_disclosure_state_user_bookmarked",
        "user_disclosure_state",
        ["user_id", "is_bookmarked"],
        schema="disclosure",
    )

    op.create_table(
        "disclosure_ai_summary",
        sa.Column(
            "summary_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("disclosure_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "summary_type",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'DISCLOSURE'"),
        ),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column(
            "prompt_version",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'v1'"),
        ),
        sa.Column("source_text_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'NOT_REQUESTED'"),
        ),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column(
            "key_points_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "risk_factors_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "financial_impacts_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "important_numbers_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "uncertainty_notes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["disclosure_id"],
            ["disclosure.dart_disclosure.disclosure_id"],
            name="fk_disclosure_ai_summary_disclosure",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "disclosure_id",
            "summary_type",
            "model_name",
            "prompt_version",
            "source_text_hash",
            name="uq_disclosure_ai_summary_cache",
        ),
        schema="disclosure",
    )
    op.create_index(
        "ix_disclosure_ai_summary_status",
        "disclosure_ai_summary",
        ["status"],
        schema="disclosure",
    )
    op.create_index(
        "ix_disclosure_ai_summary_generated",
        "disclosure_ai_summary",
        ["generated_at"],
        schema="disclosure",
    )
    op.create_index(
        "ix_disclosure_ai_summary_disclosure",
        "disclosure_ai_summary",
        ["disclosure_id"],
        schema="disclosure",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_disclosure_ai_summary_disclosure",
        table_name="disclosure_ai_summary",
        schema="disclosure",
    )
    op.drop_index(
        "ix_disclosure_ai_summary_generated",
        table_name="disclosure_ai_summary",
        schema="disclosure",
    )
    op.drop_index(
        "ix_disclosure_ai_summary_status",
        table_name="disclosure_ai_summary",
        schema="disclosure",
    )
    op.drop_table("disclosure_ai_summary", schema="disclosure")

    op.drop_index(
        "ix_user_disclosure_state_user_bookmarked",
        table_name="user_disclosure_state",
        schema="disclosure",
    )
    op.drop_index(
        "ix_user_disclosure_state_user_read",
        table_name="user_disclosure_state",
        schema="disclosure",
    )
    op.drop_table("user_disclosure_state", schema="disclosure")

    op.drop_index(
        "ix_dart_disclosure_category_receipt",
        table_name="dart_disclosure",
        schema="disclosure",
    )
    op.drop_index(
        "ix_dart_disclosure_corp_receipt",
        table_name="dart_disclosure",
        schema="disclosure",
    )
    op.drop_index(
        "ix_dart_disclosure_stock_receipt",
        table_name="dart_disclosure",
        schema="disclosure",
    )
