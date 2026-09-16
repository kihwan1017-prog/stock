"""Add max_investment_ratio to risk setting tables

Revision ID: i2j3k4l5m6n7
Revises: g9h0i1j2k3l4
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i2j3k4l5m6n7"
down_revision: Union[str, Sequence[str], None] = "g9h0i1j2k3l4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # System: NOT NULL + 기본 0.70 (기존 realtime_risk_policy와 동일)
    op.add_column(
        "system_risk_setting",
        sa.Column(
            "max_investment_ratio",
            sa.Numeric(10, 6),
            nullable=False,
            server_default="0.70",
        ),
        schema="trading",
    )
    op.add_column(
        "user_risk_setting",
        sa.Column("max_investment_ratio", sa.Numeric(10, 6), nullable=True),
        schema="trading",
    )
    op.add_column(
        "user_broker_account_risk_setting",
        sa.Column("max_investment_ratio", sa.Numeric(10, 6), nullable=True),
        schema="trading",
    )


def downgrade() -> None:
    op.drop_column(
        "user_broker_account_risk_setting",
        "max_investment_ratio",
        schema="trading",
    )
    op.drop_column(
        "user_risk_setting", "max_investment_ratio", schema="trading"
    )
    op.drop_column(
        "system_risk_setting", "max_investment_ratio", schema="trading"
    )
