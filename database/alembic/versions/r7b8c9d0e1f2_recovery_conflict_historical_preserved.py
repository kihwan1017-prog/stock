"""STEP 8-14 — Recovery Conflict HISTORICAL_PRESERVED review_status.

Revision ID: r7b8c9d0e1f2
Revises: q6a7b8c9d0e1
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "r7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "q6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # review_status CHECK에 HISTORICAL_PRESERVED 추가
    # (환경에 따라 제약명이 ck_recovery_conflict_review 또는
    #  SQLAlchemy 자동명 ck_broker_recovery_conflict_ck_recovery_conflict_review)
    op.execute(
        "ALTER TABLE operation.broker_recovery_conflict "
        "DROP CONSTRAINT IF EXISTS ck_recovery_conflict_review"
    )
    op.execute(
        "ALTER TABLE operation.broker_recovery_conflict "
        "DROP CONSTRAINT IF EXISTS "
        "ck_broker_recovery_conflict_ck_recovery_conflict_review"
    )
    op.execute(
        """
        ALTER TABLE operation.broker_recovery_conflict
        ADD CONSTRAINT ck_recovery_conflict_review
        CHECK (
            review_status IN (
                'PENDING_REVIEW',
                'APPROVED_IMPORT',
                'IGNORED',
                'ON_HOLD',
                'REJECTED',
                'RESOLVED',
                'REMOTE_DISAPPEARED',
                'HISTORICAL_PRESERVED'
            )
        )
        """
    )


def downgrade() -> None:
    # HISTORICAL_PRESERVED 행이 있으면 downgrade 차단
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
        "ALTER TABLE operation.broker_recovery_conflict "
        "DROP CONSTRAINT IF EXISTS ck_recovery_conflict_review"
    )
    op.execute(
        """
        ALTER TABLE operation.broker_recovery_conflict
        ADD CONSTRAINT ck_recovery_conflict_review
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
