"""Daily entry LIMITED|UNLIMITED + realtime monitored symbol target.

Revision: del10x10a1b2c3
Revises: epa1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "del10x10a1b2c3"
down_revision: Union[str, Sequence[str], None] = "epa1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            ALTER TABLE operation.upbit_portfolio_policy
              ADD COLUMN IF NOT EXISTS portfolio_daily_entry_limit_mode
              VARCHAR(20) NOT NULL DEFAULT 'LIMITED'
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE operation.upbit_portfolio_policy
              DROP CONSTRAINT IF EXISTS ck_upbit_pf_daily_entry_limit_mode
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE operation.upbit_portfolio_policy
              ADD CONSTRAINT ck_upbit_pf_daily_entry_limit_mode
              CHECK (portfolio_daily_entry_limit_mode IN ('LIMITED', 'UNLIMITED'))
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE operation.upbit_portfolio_policy
              ADD COLUMN IF NOT EXISTS realtime_monitored_symbol_target
              INTEGER NULL
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            ALTER TABLE operation.upbit_portfolio_policy
              DROP CONSTRAINT IF EXISTS ck_upbit_pf_daily_entry_limit_mode
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE operation.upbit_portfolio_policy
              DROP COLUMN IF EXISTS portfolio_daily_entry_limit_mode
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE operation.upbit_portfolio_policy
              DROP COLUMN IF EXISTS realtime_monitored_symbol_target
            """
        )
    )
