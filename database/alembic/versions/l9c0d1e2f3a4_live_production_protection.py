"""STEP 8-8 — LIVE 운영 보호 (ARM·한도·슬리피지)

Revision ID: l9c0d1e2f3a4
Revises: k8b9c0d1e2f3
Create Date: 2026-07-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "l9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "k8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- UBA ARM 상태 ---
    op.add_column(
        "user_broker_account",
        sa.Column(
            "live_armed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="trading",
    )
    op.add_column(
        "user_broker_account",
        sa.Column("arm_token_hash", sa.String(64), nullable=True),
        schema="trading",
    )
    op.add_column(
        "user_broker_account",
        sa.Column(
            "arm_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="trading",
    )
    op.add_column(
        "user_broker_account",
        sa.Column("arm_armed_by", sa.String(100), nullable=True),
        schema="trading",
    )
    op.add_column(
        "user_broker_account",
        sa.Column(
            "arm_armed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="trading",
    )
    op.execute(
        sa.text(
            "UPDATE trading.user_broker_account "
            "SET live_armed = false, arm_token_hash = NULL, "
            "arm_expires_at = NULL, arm_armed_by = NULL, "
            "arm_armed_at = NULL"
        )
    )

    # --- ARM 이력 ---
    op.create_table(
        "live_arm_event",
        sa.Column(
            "live_arm_event_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column(
            "user_broker_account_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "trading.user_broker_account.user_broker_account_id",
                ondelete="CASCADE",
                name="fk_live_arm_event_uba",
            ),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("arm_token_hash", sa.String(64), nullable=True),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "detail_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="trading",
    )
    op.create_index(
        "ix_live_arm_event_uba_created",
        "live_arm_event",
        ["user_broker_account_id", "created_at"],
        schema="trading",
    )

    # --- Risk: open orders / slippage / anomaly ---
    op.add_column(
        "system_risk_setting",
        sa.Column(
            "max_open_orders",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
        schema="trading",
    )
    op.add_column(
        "system_risk_setting",
        sa.Column(
            "max_slippage_rate",
            sa.Numeric(10, 6),
            nullable=False,
            server_default="0.010000",
        ),
        schema="trading",
    )
    op.add_column(
        "system_risk_setting",
        sa.Column(
            "anomaly_orders_per_minute",
            sa.Integer(),
            nullable=False,
            server_default="10",
        ),
        schema="trading",
    )
    op.add_column(
        "system_risk_setting",
        sa.Column(
            "loop_detect_window_seconds",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
        schema="trading",
    )
    op.add_column(
        "system_risk_setting",
        sa.Column(
            "arm_ttl_seconds",
            sa.Integer(),
            nullable=False,
            server_default="300",
        ),
        schema="trading",
    )

    for table in ("user_risk_setting", "user_broker_account_risk_setting"):
        op.add_column(
            table,
            sa.Column("max_open_orders", sa.Integer(), nullable=True),
            schema="trading",
        )
        op.add_column(
            table,
            sa.Column(
                "max_slippage_rate",
                sa.Numeric(10, 6),
                nullable=True,
            ),
            schema="trading",
        )
        op.add_column(
            table,
            sa.Column(
                "anomaly_orders_per_minute",
                sa.Integer(),
                nullable=True,
            ),
            schema="trading",
        )
        op.add_column(
            table,
            sa.Column(
                "loop_detect_window_seconds",
                sa.Integer(),
                nullable=True,
            ),
            schema="trading",
        )
        op.add_column(
            table,
            sa.Column("arm_ttl_seconds", sa.Integer(), nullable=True),
            schema="trading",
        )


def downgrade() -> None:
    for table in (
        "user_broker_account_risk_setting",
        "user_risk_setting",
        "system_risk_setting",
    ):
        for col in (
            "arm_ttl_seconds",
            "loop_detect_window_seconds",
            "anomaly_orders_per_minute",
            "max_slippage_rate",
            "max_open_orders",
        ):
            op.drop_column(table, col, schema="trading")

    op.drop_index(
        "ix_live_arm_event_uba_created",
        table_name="live_arm_event",
        schema="trading",
    )
    op.drop_table("live_arm_event", schema="trading")

    for col in (
        "arm_armed_at",
        "arm_armed_by",
        "arm_expires_at",
        "arm_token_hash",
        "live_armed",
    ):
        op.drop_column("user_broker_account", col, schema="trading")
