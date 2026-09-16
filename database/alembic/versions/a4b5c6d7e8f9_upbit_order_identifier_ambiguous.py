"""STEP 8-5-12 — Upbit order identifier / ambiguous columns.

Revision ID: a4b5c6d7e8f9
Revises: z3d4e5f6a7b8
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, Sequence[str], None] = "z3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 기존 Upbit 주문에 가짜 Identifier를 만들어 외부 조회에 쓰지 않음
    op.add_column(
        "trading_order",
        sa.Column(
            "client_order_identifier", sa.String(36), nullable=True
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column(
            "submission_generation",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column(
            "first_submitted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column(
            "last_submission_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column(
            "submission_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column(
            "ambiguous_since",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column("ambiguity_reason", sa.String(200), nullable=True),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column(
            "remote_lookup_status", sa.String(40), nullable=True
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column(
            "remote_lookup_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column(
            "last_remote_lookup_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column(
            "next_remote_lookup_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column("source_signal_id", sa.String(100), nullable=True),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column(
            "source_signal_fingerprint", sa.String(64), nullable=True
        ),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column("order_fingerprint", sa.String(64), nullable=True),
        schema="trading",
    )

    op.create_index(
        "ix_trading_order_next_remote_lookup",
        "trading_order",
        ["next_remote_lookup_at"],
        schema="trading",
    )
    op.create_index(
        "ix_trading_order_ambiguous_since",
        "trading_order",
        ["broker_code", "status_code", "ambiguous_since"],
        schema="trading",
    )
    # UBA + Identifier Unique (NULL identifier 허용 — partial unique)
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_trading_order_uba_client_identifier
            ON trading.trading_order (
                user_broker_account_id, client_order_identifier
            )
            WHERE client_order_identifier IS NOT NULL
              AND client_order_identifier <> ''
            """
        )
    )
    op.create_check_constraint(
        "ck_trading_order_submission_generation_pos",
        "trading_order",
        "submission_generation >= 1",
        schema="trading",
    )
    op.create_check_constraint(
        "ck_trading_order_submission_attempt_nonneg",
        "trading_order",
        "submission_attempt_count >= 0",
        schema="trading",
    )
    op.create_check_constraint(
        "ck_trading_order_remote_lookup_attempt_nonneg",
        "trading_order",
        "remote_lookup_attempt_count >= 0",
        schema="trading",
    )

    op.create_table(
        "order_submission_attempt",
        sa.Column(
            "attempt_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "client_order_identifier", sa.String(36), nullable=True
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("result_type", sa.String(40), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("upbit_error_code", sa.String(80), nullable=True),
        sa.Column(
            "external_order_uuid", sa.String(100), nullable=True
        ),
        sa.Column(
            "ambiguous",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("retry_action", sa.String(40), nullable=True),
        sa.Column("correlation_id", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["trading.trading_order.order_id"],
            name="fk_order_submission_attempt_order",
            ondelete="CASCADE",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_order_submission_attempt_order",
        "order_submission_attempt",
        ["order_id", "attempt_number"],
        schema="trading",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_order_submission_attempt_order",
        table_name="order_submission_attempt",
        schema="trading",
    )
    op.drop_table("order_submission_attempt", schema="trading")
    op.drop_constraint(
        "ck_trading_order_remote_lookup_attempt_nonneg",
        "trading_order",
        schema="trading",
        type_="check",
    )
    op.drop_constraint(
        "ck_trading_order_submission_attempt_nonneg",
        "trading_order",
        schema="trading",
        type_="check",
    )
    op.drop_constraint(
        "ck_trading_order_submission_generation_pos",
        "trading_order",
        schema="trading",
        type_="check",
    )
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS trading.uq_trading_order_uba_client_identifier"
        )
    )
    op.drop_index(
        "ix_trading_order_ambiguous_since",
        table_name="trading_order",
        schema="trading",
    )
    op.drop_index(
        "ix_trading_order_next_remote_lookup",
        table_name="trading_order",
        schema="trading",
    )
    for col in (
        "order_fingerprint",
        "source_signal_fingerprint",
        "source_signal_id",
        "next_remote_lookup_at",
        "last_remote_lookup_at",
        "remote_lookup_attempt_count",
        "remote_lookup_status",
        "ambiguity_reason",
        "ambiguous_since",
        "submission_attempt_count",
        "last_submission_attempt_at",
        "first_submitted_at",
        "submission_generation",
        "client_order_identifier",
    ):
        op.drop_column("trading_order", col, schema="trading")
