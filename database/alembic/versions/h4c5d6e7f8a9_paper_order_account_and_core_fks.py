"""P0 — paper_order.account_id + core FK hardening

Revision ID: h4c5d6e7f8a9
Revises: g3b4c5d6e7f8
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "g3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- paper_order.account_id (Critical) ---
    op.add_column(
        "paper_order",
        sa.Column("account_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    # paper_trade → account_id 백필 (있으면)
    op.execute(
        """
        UPDATE trading.paper_order AS po
        SET account_id = src.account_id
        FROM (
            SELECT DISTINCT ON (order_id) order_id, account_id
            FROM trading.paper_trade
            WHERE order_id IS NOT NULL
            ORDER BY order_id, trade_id
        ) AS src
        WHERE po.order_id = src.order_id
          AND po.account_id IS NULL
        """
    )
    # 잔여 orphan → 최소 paper_account (없으면 삭제)
    op.execute(
        """
        UPDATE trading.paper_order
        SET account_id = (
            SELECT MIN(account_id) FROM trading.paper_account
        )
        WHERE account_id IS NULL
          AND EXISTS (SELECT 1 FROM trading.paper_account)
        """
    )
    op.execute(
        """
        DELETE FROM trading.paper_order
        WHERE account_id IS NULL
        """
    )
    op.alter_column(
        "paper_order",
        "account_id",
        existing_type=sa.BigInteger(),
        nullable=False,
        schema="trading",
    )
    op.create_index(
        "ix_paper_order_account_id",
        "paper_order",
        ["account_id"],
        unique=False,
        schema="trading",
    )
    op.create_foreign_key(
        "fk_paper_order_account",
        "paper_order",
        "paper_account",
        ["account_id"],
        ["account_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_paper_order_position_plan",
        "paper_order",
        "position_plan",
        ["position_plan_id"],
        ["position_plan_id"],
        source_schema="trading",
        referent_schema="strategy",
        ondelete="SET NULL",
    )

    # --- preference default_* FK ---
    op.execute(
        """
        UPDATE auth.user_preference p
        SET default_account_id = NULL
        WHERE default_account_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM trading.paper_account a
            WHERE a.account_id = p.default_account_id
          )
        """
    )
    op.execute(
        """
        UPDATE auth.user_preference p
        SET default_watchlist_id = NULL
        WHERE default_watchlist_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM trading.watchlist w
            WHERE w.watchlist_id = p.default_watchlist_id
          )
        """
    )
    op.create_foreign_key(
        "fk_user_preference_default_account",
        "user_preference",
        "paper_account",
        ["default_account_id"],
        ["account_id"],
        source_schema="auth",
        referent_schema="trading",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_user_preference_default_watchlist",
        "user_preference",
        "watchlist",
        ["default_watchlist_id"],
        ["watchlist_id"],
        source_schema="auth",
        referent_schema="trading",
        ondelete="SET NULL",
    )

    # --- trading_order 자기참조 ---
    op.execute(
        """
        UPDATE trading.trading_order o
        SET original_order_id = NULL
        WHERE original_order_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM trading.trading_order p
            WHERE p.order_id = o.original_order_id
          )
        """
    )
    op.execute(
        """
        UPDATE trading.trading_order o
        SET replaced_order_id = NULL
        WHERE replaced_order_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM trading.trading_order p
            WHERE p.order_id = o.replaced_order_id
          )
        """
    )
    op.create_foreign_key(
        "fk_trading_order_original",
        "trading_order",
        "trading_order",
        ["original_order_id"],
        ["order_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_trading_order_replaced",
        "trading_order",
        "trading_order",
        ["replaced_order_id"],
        ["order_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )

    # --- strategy deployment 그래프 ---
    op.create_foreign_key(
        "fk_strategy_deployment_performance_run",
        "strategy_deployment",
        "strategy_performance_run",
        ["strategy_performance_run_id"],
        ["strategy_performance_run_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_strategy_deployment_replaced_by",
        "strategy_deployment",
        "strategy_deployment",
        ["replaced_by_deployment_id"],
        ["strategy_deployment_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_strategy_runtime_switch_previous",
        "strategy_runtime_switch",
        "strategy_deployment",
        ["previous_deployment_id"],
        ["strategy_deployment_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_strategy_runtime_switch_target",
        "strategy_runtime_switch",
        "strategy_deployment",
        ["target_deployment_id"],
        ["strategy_deployment_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_strategy_approval_performance_run",
        "strategy_approval_run",
        "strategy_performance_run",
        ["strategy_performance_run_id"],
        ["strategy_performance_run_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_strategy_approval_selection_run",
        "strategy_approval_run",
        "strategy_selection_run",
        ["strategy_selection_run_id"],
        ["strategy_selection_run_id"],
        source_schema="trading",
        referent_schema="ai",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_strategy_approval_deployment",
        "strategy_approval_run",
        "strategy_deployment",
        ["deployment_id"],
        ["strategy_deployment_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    for name, table, schema in (
        ("fk_strategy_approval_deployment", "strategy_approval_run", "trading"),
        ("fk_strategy_approval_selection_run", "strategy_approval_run", "trading"),
        ("fk_strategy_approval_performance_run", "strategy_approval_run", "trading"),
        ("fk_strategy_runtime_switch_target", "strategy_runtime_switch", "trading"),
        ("fk_strategy_runtime_switch_previous", "strategy_runtime_switch", "trading"),
        ("fk_strategy_deployment_replaced_by", "strategy_deployment", "trading"),
        ("fk_strategy_deployment_performance_run", "strategy_deployment", "trading"),
        ("fk_trading_order_replaced", "trading_order", "trading"),
        ("fk_trading_order_original", "trading_order", "trading"),
        ("fk_user_preference_default_watchlist", "user_preference", "auth"),
        ("fk_user_preference_default_account", "user_preference", "auth"),
        ("fk_paper_order_position_plan", "paper_order", "trading"),
        ("fk_paper_order_account", "paper_order", "trading"),
    ):
        op.drop_constraint(name, table, schema=schema, type_="foreignkey")

    op.drop_index(
        "ix_paper_order_account_id",
        table_name="paper_order",
        schema="trading",
    )
    op.drop_column("paper_order", "account_id", schema="trading")
