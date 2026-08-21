"""Additive: uba_daily_equity_baseline.equity_policy_version."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s0t1u2v3w4x5"
down_revision: Union[str, Sequence[str], None] = "r9s0t1u2v3w4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "uba_daily_equity_baseline",
        sa.Column("equity_policy_version", sa.String(length=80), nullable=True),
        schema="operation",
    )


def downgrade() -> None:
    op.drop_column(
        "uba_daily_equity_baseline",
        "equity_policy_version",
        schema="operation",
    )
