"""Additive: strategy_position_binding + strategy_daily_pnl + equity_policy_version."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "t1u2v3w4x5y6"
down_revision: Union[str, Sequence[str], None] = "s0t1u2v3w4x5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS operation"))

    # settlement V2 column — idempotent if s0 already applied
    op.execute(
        sa.text(
            """
            ALTER TABLE operation.uba_daily_equity_baseline
            ADD COLUMN IF NOT EXISTS equity_policy_version VARCHAR(80)
            """
        )
    )

    op.create_table(
        "strategy_position_binding",
        sa.Column("binding_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("broker_code", sa.String(length=30), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=False),
        sa.Column("deployment_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'OPEN'"),
            nullable=False,
        ),
        sa.Column(
            "ownership_code",
            sa.String(length=30),
            server_default=sa.text("'STRATEGY_OWNED'"),
            nullable=False,
        ),
        sa.Column("entry_order_id", sa.BigInteger(), nullable=True),
        sa.Column("broker_order_id", sa.String(length=80), nullable=True),
        sa.Column(
            "owned_quantity",
            sa.Numeric(20, 8),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=True),
        sa.Column(
            "realized_pnl",
            sa.Numeric(20, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "fees",
            sa.Numeric(20, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "meta_json",
            postgresql.JSONB(),
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
            "strategy_id",
            "symbol",
            "entry_order_id",
            name="uq_strategy_position_binding_entry",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_strategy_position_binding_uba",
        "strategy_position_binding",
        ["user_broker_account_id"],
        schema="operation",
    )
    op.create_index(
        "ix_strategy_position_binding_strategy",
        "strategy_position_binding",
        ["strategy_id"],
        schema="operation",
    )

    op.create_table(
        "strategy_daily_pnl",
        sa.Column(
            "strategy_daily_pnl_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("broker_code", sa.String(length=30), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "deployment_id",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "opening_strategy_equity",
            sa.Numeric(20, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "realized_pnl",
            sa.Numeric(20, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "unrealized_pnl",
            sa.Numeric(20, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "fees",
            sa.Numeric(20, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "current_pnl",
            sa.Numeric(20, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "current_loss_amount",
            sa.Numeric(20, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("loss_limit_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column(
            "entry_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "closed_trade_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "consecutive_losses",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "open_binding_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "status_code",
            sa.String(length=30),
            server_default=sa.text("'SAFE'"),
            nullable=False,
        ),
        sa.Column(
            "meta_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "trading_date",
            "broker_code",
            "user_broker_account_id",
            "strategy_id",
            "deployment_id",
            name="uq_strategy_daily_pnl_scope",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_strategy_daily_pnl_uba",
        "strategy_daily_pnl",
        ["user_broker_account_id"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_strategy_daily_pnl_uba",
        table_name="strategy_daily_pnl",
        schema="operation",
    )
    op.drop_table("strategy_daily_pnl", schema="operation")
    op.drop_index(
        "ix_strategy_position_binding_strategy",
        table_name="strategy_position_binding",
        schema="operation",
    )
    op.drop_index(
        "ix_strategy_position_binding_uba",
        table_name="strategy_position_binding",
        schema="operation",
    )
    op.drop_table("strategy_position_binding", schema="operation")
