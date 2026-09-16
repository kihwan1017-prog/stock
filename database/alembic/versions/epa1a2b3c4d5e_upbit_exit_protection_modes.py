"""UPBIT Exit Policy Alignment V1 — explicit REAL exit protection modes.

Adds tri-state modes on user/UBA risk settings:
  INHERIT | ENABLED | DISABLED

Default INHERIT preserves existing NULL-rate inheritance behavior.
Does NOT mutate trading.system_risk_setting.DEFAULT rates.

Revises: tav2a1b2c3d4e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "epa1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "tav2a1b2c3d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MODE_COLS = (
    "stop_loss_mode",
    "take_profit_mode",
    "trailing_stop_mode",
)


def upgrade() -> None:
    for table in (
        "trading.user_risk_setting",
        "trading.user_broker_account_risk_setting",
    ):
        for col in _MODE_COLS:
            op.execute(
                sa.text(
                    f"""
                    ALTER TABLE {table}
                      ADD COLUMN IF NOT EXISTS {col}
                      VARCHAR(20) NOT NULL DEFAULT 'INHERIT'
                    """
                )
            )
            op.execute(
                sa.text(
                    f"""
                    ALTER TABLE {table}
                      DROP CONSTRAINT IF EXISTS ck_{table.split('.')[-1]}_{col}
                    """
                )
            )
            # CHECK: 허용 값만
            short = table.split(".")[-1]
            op.execute(
                sa.text(
                    f"""
                    ALTER TABLE {table}
                      ADD CONSTRAINT ck_{short}_{col}
                      CHECK ({col} IN ('INHERIT', 'ENABLED', 'DISABLED'))
                    """
                )
            )


def downgrade() -> None:
    for table in (
        "trading.user_broker_account_risk_setting",
        "trading.user_risk_setting",
    ):
        short = table.split(".")[-1]
        for col in _MODE_COLS:
            op.execute(
                sa.text(
                    f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{short}_{col}"
                )
            )
            op.execute(
                sa.text(
                    f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}"
                )
            )
