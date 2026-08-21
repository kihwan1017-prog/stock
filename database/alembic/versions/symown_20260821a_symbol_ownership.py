"""Additive Symbol Ownership exclusion/hold tables.

Revision ID: symown_20260821a
Revises: t1u2v3w4x5y6
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "symown_20260821a"
down_revision: Union[str, Sequence[str], None] = "t1u2v3w4x5y6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS operation")
    op.create_table(
        "symbol_auto_exclusion",
        sa.Column("symbol_auto_exclusion_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("broker_code", sa.String(30), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("reason", sa.String(200)),
        sa.Column("created_by", sa.String(80)),
        sa.Column(
            "meta_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_broker_account_id",
            "broker_code",
            "symbol",
            name="uq_symbol_auto_exclusion_uba_broker_symbol",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_symbol_auto_exclusion_uba",
        "symbol_auto_exclusion",
        ["user_broker_account_id"],
        schema="operation",
    )
    op.create_table(
        "symbol_ownership_hold",
        sa.Column("symbol_ownership_hold_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("broker_code", sa.String(30), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column(
            "status",
            sa.String(30),
            server_default=sa.text("'ACTIVE'"),
            nullable=False,
        ),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column(
            "detail_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cleared_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_broker_account_id",
            "broker_code",
            "symbol",
            name="uq_symbol_ownership_hold_uba_broker_symbol",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_symbol_ownership_hold_uba",
        "symbol_ownership_hold",
        ["user_broker_account_id"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_table("symbol_ownership_hold", schema="operation")
    op.drop_table("symbol_auto_exclusion", schema="operation")
