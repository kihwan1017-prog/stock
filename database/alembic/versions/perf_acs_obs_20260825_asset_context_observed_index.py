"""revision: perf_acs_obs_20260825

EXPLAIN 근거: upbit_asset_context_snapshot ORDER BY observed_at DESC 가
Seq Scan + external merge(Disk) → Index Scan 으로 전환.

CREATE INDEX CONCURRENTLY 로 운영 적용 가능.
REAL 주문/정책 변경 없음.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "perf_acs_obs_20260825"
down_revision = "v2w3x4y5z6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 트랜잭션 밖 CONCURRENTLY — 락 최소화
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                """
                CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_upbit_asset_ctx_observed_at
                ON operation.upbit_asset_context_snapshot (observed_at DESC)
                """
            )
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                "DROP INDEX CONCURRENTLY IF EXISTS operation.ix_upbit_asset_ctx_observed_at"
            )
        )
