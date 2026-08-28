"""revision: uei1a2b3c4d5e

UPBIT durable exit intent + bounded retry (WRK-014).
Historical backfill 없음. REAL BUY/MA threshold 변경 없음.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "uei1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "perf_ueet_uba_created_20260829"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_exit_intent",
        sa.Column("exit_intent_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("slot_id", sa.BigInteger(), nullable=True),
        sa.Column("binding_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column(
            "exit_reason",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'MA_DEAD_CROSS'"),
        ),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("strategy_version", sa.String(120), nullable=True),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'CONFIRMED'"),
        ),
        sa.Column("initial_signal_id", sa.String(100), nullable=True),
        sa.Column("initial_order_id", sa.BigInteger(), nullable=True),
        sa.Column("last_order_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "initial_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "max_retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
        sa.Column("initial_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("remaining_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("last_condition_result", sa.String(40), nullable=True),
        sa.Column(
            "last_condition_checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_block_reason", sa.String(80), nullable=True),
        sa.Column(
            "detail_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "event_log_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="operation",
    )
    # 활성 intent 1개/UBA+symbol — partial unique
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_uei_active_uba_symbol
            ON operation.upbit_exit_intent (user_broker_account_id, symbol)
            WHERE status IN (
              'CONFIRMED', 'ORDER_PENDING', 'COOLDOWN',
              'REVALIDATING', 'BLOCKED'
            )
            """
        )
    )
    op.create_index(
        "ix_uei_uba_status",
        "upbit_exit_intent",
        ["user_broker_account_id", "status"],
        schema="operation",
    )
    op.create_index(
        "ix_uei_uba_symbol_status",
        "upbit_exit_intent",
        ["user_broker_account_id", "symbol", "status"],
        schema="operation",
    )
    op.create_index(
        "ix_uei_next_retry_at",
        "upbit_exit_intent",
        ["next_retry_at"],
        schema="operation",
    )
    op.create_index(
        "ix_uei_binding_id",
        "upbit_exit_intent",
        ["binding_id"],
        schema="operation",
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS operation.uq_uei_active_uba_symbol"))
    op.drop_index("ix_uei_binding_id", table_name="upbit_exit_intent", schema="operation")
    op.drop_index("ix_uei_next_retry_at", table_name="upbit_exit_intent", schema="operation")
    op.drop_index(
        "ix_uei_uba_symbol_status",
        table_name="upbit_exit_intent",
        schema="operation",
    )
    op.drop_index("ix_uei_uba_status", table_name="upbit_exit_intent", schema="operation")
    op.drop_table("upbit_exit_intent", schema="operation")
