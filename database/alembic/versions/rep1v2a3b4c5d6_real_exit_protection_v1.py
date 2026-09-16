"""REAL Exit Protection V1 — trailing activation + max hold.

Revision ID: rep1v2a3b4c5d6
Revises: del10x10a1b2c3
Create Date: 2026-08-30

Adds:
- trailing_activation_rate (fraction, e.g. 0.01 = +1%)
- max_hold_mode (INHERIT|ENABLED|DISABLED)
- max_hold_seconds (e.g. 21600 = 6h)

on user_risk_setting and user_broker_account_risk_setting.
Does NOT change existing UBA rows to ENABLED (application step does).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "rep1v2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "del10x10a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in (
        "trading.user_risk_setting",
        "trading.user_broker_account_risk_setting",
    ):
        op.add_column(
            table.split(".", 1)[1],
            sa.Column(
                "trailing_activation_rate",
                sa.Numeric(10, 6),
                nullable=True,
            ),
            schema=table.split(".", 1)[0],
        )
        op.add_column(
            table.split(".", 1)[1],
            sa.Column(
                "max_hold_mode",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'INHERIT'"),
            ),
            schema=table.split(".", 1)[0],
        )
        op.add_column(
            table.split(".", 1)[1],
            sa.Column(
                "max_hold_seconds",
                sa.Integer(),
                nullable=True,
            ),
            schema=table.split(".", 1)[0],
        )


def downgrade() -> None:
    for table in (
        "trading.user_broker_account_risk_setting",
        "trading.user_risk_setting",
    ):
        schema, name = table.split(".", 1)
        op.drop_column(name, "max_hold_seconds", schema=schema)
        op.drop_column(name, "max_hold_mode", schema=schema)
        op.drop_column(name, "trailing_activation_rate", schema=schema)
