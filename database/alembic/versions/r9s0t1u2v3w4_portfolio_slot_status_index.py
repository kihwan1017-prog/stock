"""revision: r9s0t1u2v3w4

Portfolio slot active-symbol unique index — SELECTED/WARMING_UP/WAITING_SIGNAL 포함.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r9s0t1u2v3w4"
down_revision = "q8r9s0t1u2v3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS operation.uq_upbit_slot_uba_active_symbol"
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_upbit_slot_uba_active_symbol
            ON operation.upbit_position_slot (user_broker_account_id, symbol)
            WHERE symbol IS NOT NULL
              AND status IN (
                'SELECTED', 'WARMING_UP', 'WAITING_SIGNAL',
                'RESERVED', 'ENTRY_PENDING', 'OPEN', 'EXIT_PENDING'
              )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS operation.uq_upbit_slot_uba_active_symbol"
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_upbit_slot_uba_active_symbol
            ON operation.upbit_position_slot (user_broker_account_id, symbol)
            WHERE symbol IS NOT NULL
              AND status IN (
                'RESERVED', 'ENTRY_PENDING', 'OPEN', 'EXIT_PENDING'
              )
            """
        )
    )
