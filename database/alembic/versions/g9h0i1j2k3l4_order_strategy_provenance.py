"""Order/Trade strategy provenance + indicator parameter configs

Revision ID: g9h0i1j2k3l4
Revises: a7f3e91c4d28
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "g9h0i1j2k3l4"
down_revision = "a7f3e91c4d28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trading_order",
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column("strategy_version", sa.Integer(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column("runtime_scope_hash", sa.String(length=128), nullable=True),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column("account_strategy_link_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "trading_order",
        sa.Column("execution_mode", sa.String(length=30), nullable=True),
        schema="trading",
    )
    op.create_foreign_key(
        "fk_trading_order_strategy_id",
        "trading_order",
        "strategy_definition",
        ["strategy_id"],
        ["strategy_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_trading_order_account_strategy_link",
        "trading_order",
        "account_strategy_link",
        ["account_strategy_link_id"],
        ["account_strategy_link_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_trading_order_strategy_perf",
        "trading_order",
        ["account_id", "strategy_id", "created_at"],
        schema="trading",
    )

    op.add_column(
        "paper_order",
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "paper_order",
        sa.Column("strategy_version", sa.Integer(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "paper_order",
        sa.Column("runtime_scope_hash", sa.String(length=128), nullable=True),
        schema="trading",
    )
    op.add_column(
        "paper_order",
        sa.Column("account_strategy_link_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "paper_order",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "paper_order",
        sa.Column("execution_mode", sa.String(length=30), nullable=True),
        schema="trading",
    )
    op.create_foreign_key(
        "fk_paper_order_strategy_id",
        "paper_order",
        "strategy_definition",
        ["strategy_id"],
        ["strategy_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_paper_order_strategy_perf",
        "paper_order",
        ["account_id", "strategy_id", "created_at"],
        schema="trading",
    )

    op.add_column(
        "paper_trade",
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "paper_trade",
        sa.Column("strategy_version", sa.Integer(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "paper_trade",
        sa.Column("runtime_scope_hash", sa.String(length=128), nullable=True),
        schema="trading",
    )
    op.add_column(
        "paper_trade",
        sa.Column("account_strategy_link_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "paper_trade",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "paper_trade",
        sa.Column("execution_mode", sa.String(length=30), nullable=True),
        schema="trading",
    )
    op.create_foreign_key(
        "fk_paper_trade_strategy_id",
        "paper_trade",
        "strategy_definition",
        ["strategy_id"],
        ["strategy_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_paper_trade_strategy_perf",
        "paper_trade",
        ["account_id", "strategy_id", "traded_at"],
        schema="trading",
    )

    op.create_table(
        "indicator_parameter_config",
        sa.Column(
            "indicator_parameter_config_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("indicator_code", sa.String(length=40), nullable=False),
        sa.Column(
            "market_type",
            sa.String(length=20),
            nullable=False,
            server_default="STOCK",
        ),
        sa.Column("exchange_code", sa.String(length=20), nullable=True),
        sa.Column(
            "timeframe",
            sa.String(length=20),
            nullable=False,
            server_default="1D",
        ),
        sa.Column(
            "parameter_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.String(length=100), nullable=True),
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
        schema="market",
    )
    op.create_index(
        "ix_indicator_param_active",
        "indicator_parameter_config",
        ["indicator_code", "market_type", "timeframe", "is_active"],
        schema="market",
    )


def downgrade() -> None:
    op.drop_table("indicator_parameter_config", schema="market")

    op.drop_index(
        "ix_paper_trade_strategy_perf",
        table_name="paper_trade",
        schema="trading",
    )
    op.drop_constraint(
        "fk_paper_trade_strategy_id",
        "paper_trade",
        schema="trading",
        type_="foreignkey",
    )
    for col in (
        "execution_mode",
        "user_id",
        "account_strategy_link_id",
        "runtime_scope_hash",
        "strategy_version",
        "strategy_id",
    ):
        op.drop_column("paper_trade", col, schema="trading")

    op.drop_index(
        "ix_paper_order_strategy_perf",
        table_name="paper_order",
        schema="trading",
    )
    op.drop_constraint(
        "fk_paper_order_strategy_id",
        "paper_order",
        schema="trading",
        type_="foreignkey",
    )
    for col in (
        "execution_mode",
        "user_id",
        "account_strategy_link_id",
        "runtime_scope_hash",
        "strategy_version",
        "strategy_id",
    ):
        op.drop_column("paper_order", col, schema="trading")

    op.drop_index(
        "ix_trading_order_strategy_perf",
        table_name="trading_order",
        schema="trading",
    )
    op.drop_constraint(
        "fk_trading_order_account_strategy_link",
        "trading_order",
        schema="trading",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_trading_order_strategy_id",
        "trading_order",
        schema="trading",
        type_="foreignkey",
    )
    for col in (
        "execution_mode",
        "user_id",
        "account_strategy_link_id",
        "runtime_scope_hash",
        "strategy_version",
        "strategy_id",
    ):
        op.drop_column("trading_order", col, schema="trading")
