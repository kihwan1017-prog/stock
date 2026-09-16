"""UPBIT entry execution trace — append-only provenance (REAL policy unchanged).

Revision ID: ue1a2b3c4d5e
Revises: md1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ue1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "md1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_entry_execution_trace",
        sa.Column("trace_row_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("execution_trace_id", sa.String(36), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("selection_id", sa.BigInteger(), nullable=True),
        sa.Column("candidate_id", sa.BigInteger(), nullable=True),
        sa.Column("waiting_id", sa.BigInteger(), nullable=True),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column(
            "lifecycle_kind",
            sa.String(24),
            nullable=False,
            server_default=sa.text("'INITIAL'"),
        ),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("reason_detail", sa.Text(), nullable=True),
        sa.Column("signal_id", sa.String(100), nullable=True),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("outbox_id", sa.BigInteger(), nullable=True),
        sa.Column("related_object_id", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column(
            "detail_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_ueet_idempotency_key"),
        schema="operation",
    )
    op.create_index(
        "ix_ueet_execution_trace_id",
        "upbit_entry_execution_trace",
        ["execution_trace_id"],
        schema="operation",
    )
    op.create_index(
        "ix_ueet_uba_selection_created",
        "upbit_entry_execution_trace",
        ["user_broker_account_id", "selection_id", "created_at"],
        schema="operation",
    )
    op.create_index(
        "ix_ueet_symbol_created",
        "upbit_entry_execution_trace",
        ["symbol", "created_at"],
        schema="operation",
    )
    op.create_index(
        "ix_ueet_order_id",
        "upbit_entry_execution_trace",
        ["order_id"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index("ix_ueet_order_id", table_name="upbit_entry_execution_trace", schema="operation")
    op.drop_index("ix_ueet_symbol_created", table_name="upbit_entry_execution_trace", schema="operation")
    op.drop_index("ix_ueet_uba_selection_created", table_name="upbit_entry_execution_trace", schema="operation")
    op.drop_index("ix_ueet_execution_trace_id", table_name="upbit_entry_execution_trace", schema="operation")
    op.drop_table("upbit_entry_execution_trace", schema="operation")
