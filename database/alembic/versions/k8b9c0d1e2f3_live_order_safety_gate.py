"""STEP 8-7 — LIVE 주문 안전 게이트 (계좌 LIVE 승인·수량/횟수/중복 창)

Revision ID: k8b9c0d1e2f3
Revises: j3d4e5f6a7b8
Create Date: 2026-07-26

- user_broker_account.live_order_enabled 기본 OFF (기존 계좌 포함)
- risk settings: max_order_quantity, daily_order_limit, duplicate_order_window_seconds
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "j3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- UBA LIVE 승인 (기본 OFF — Fail Closed) ---
    op.add_column(
        "user_broker_account",
        sa.Column(
            "live_order_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="trading",
    )
    op.add_column(
        "user_broker_account",
        sa.Column(
            "live_approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="trading",
    )
    op.add_column(
        "user_broker_account",
        sa.Column(
            "live_approved_by",
            sa.String(100),
            nullable=True,
        ),
        schema="trading",
    )
    # 운영 중 기존 계좌도 명시적으로 OFF
    op.execute(
        sa.text(
            "UPDATE trading.user_broker_account "
            "SET live_order_enabled = false"
        )
    )

    # --- System risk: 수량·일일횟수·중복창 ---
    op.add_column(
        "system_risk_setting",
        sa.Column(
            "max_order_quantity",
            sa.Numeric(28, 8),
            nullable=False,
            server_default="100",
        ),
        schema="trading",
    )
    op.add_column(
        "system_risk_setting",
        sa.Column(
            "daily_order_limit",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
        schema="trading",
    )
    op.add_column(
        "system_risk_setting",
        sa.Column(
            "duplicate_order_window_seconds",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        schema="trading",
    )

    for table in (
        "user_risk_setting",
        "user_broker_account_risk_setting",
    ):
        op.add_column(
            table,
            sa.Column(
                "max_order_quantity",
                sa.Numeric(28, 8),
                nullable=True,
            ),
            schema="trading",
        )
        op.add_column(
            table,
            sa.Column(
                "daily_order_limit",
                sa.Integer(),
                nullable=True,
            ),
            schema="trading",
        )
        op.add_column(
            table,
            sa.Column(
                "duplicate_order_window_seconds",
                sa.Integer(),
                nullable=True,
            ),
            schema="trading",
        )


def downgrade() -> None:
    for table in (
        "user_broker_account_risk_setting",
        "user_risk_setting",
        "system_risk_setting",
    ):
        op.drop_column(table, "duplicate_order_window_seconds", schema="trading")
        op.drop_column(table, "daily_order_limit", schema="trading")
        op.drop_column(table, "max_order_quantity", schema="trading")

    op.drop_column("user_broker_account", "live_approved_by", schema="trading")
    op.drop_column("user_broker_account", "live_approved_at", schema="trading")
    op.drop_column("user_broker_account", "live_order_enabled", schema="trading")
