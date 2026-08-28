"""revision: perf_ueet_uba_created_20260829

EXPLAIN 근거: upbit_entry_execution_trace 일별 pipeline COUNT가
Parallel Seq Scan (Buffers read~11k) → uba+created_at Index Scan 유도.

CREATE INDEX CONCURRENTLY.
REAL 주문/정책 변경 없음.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "perf_ueet_uba_created_20260829"
down_revision = "dw1a2b3c4d5e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                """
                CREATE INDEX CONCURRENTLY IF NOT EXISTS
                  ix_ueet_uba_created_at
                ON operation.upbit_entry_execution_trace
                  (user_broker_account_id, created_at)
                """
            )
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                "DROP INDEX CONCURRENTLY IF EXISTS operation.ix_ueet_uba_created_at"
            )
        )
