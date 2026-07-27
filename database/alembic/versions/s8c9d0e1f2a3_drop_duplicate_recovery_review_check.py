"""STEP 8-15 — drop duplicate review_status CHECK without HISTORICAL_PRESERVED.

Revision ID: s8c9d0e1f2a3
Revises: r7b8c9d0e1f2
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "s8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "r7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLAlchemy 자동명 구제약(HISTORICAL_PRESERVED 미포함) 제거
    op.execute(
        "ALTER TABLE operation.broker_recovery_conflict "
        "DROP CONSTRAINT IF EXISTS "
        "ck_broker_recovery_conflict_ck_recovery_conflict_review"
    )
    # r7에서 추가한 ck_recovery_conflict_review 가 HISTORICAL_PRESERVED 포함


def downgrade() -> None:
    # 구제약 복원 시 HISTORICAL_PRESERVED 행이 있으면 실패
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM operation.broker_recovery_conflict
                WHERE review_status = 'HISTORICAL_PRESERVED'
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade: HISTORICAL_PRESERVED rows exist';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        ALTER TABLE operation.broker_recovery_conflict
        ADD CONSTRAINT ck_broker_recovery_conflict_ck_recovery_conflict_review
        CHECK (
            review_status IN (
                'PENDING_REVIEW',
                'APPROVED_IMPORT',
                'IGNORED',
                'ON_HOLD',
                'REJECTED',
                'RESOLVED',
                'REMOTE_DISAPPEARED'
            )
        )
        """
    )
