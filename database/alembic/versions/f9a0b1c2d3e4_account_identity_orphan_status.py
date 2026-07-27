"""STEP 8-5-18 — Account Identity: ORPHAN 상태 확장.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_STATUSES = (
    "'ACTIVE','ORPHAN','STALE','SUPERSEDED','INVALID',"
    "'REBIND_PENDING','REBOUND','RETIRED','PURGED'"
)
_OLD_STATUSES = (
    "'ACTIVE','ORPHAN','STALE','SUPERSEDED','INVALID'"
)


def upgrade() -> None:
    # account snapshot 상태 확장
    op.drop_constraint(
        "ck_broker_account_snapshot_status",
        "broker_account_snapshot",
        schema="trading",
        type_="check",
    )
    op.create_check_constraint(
        "ck_broker_account_snapshot_status",
        "broker_account_snapshot",
        f"snapshot_status IN ({_NEW_STATUSES})",
        schema="trading",
    )

    # position snapshot 동일 제약 (존재 시)
    bind = op.get_bind()
    pos_ck = bind.execute(
        sa.text(
            """
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_broker_position_snapshot_status'
            """
        )
    ).scalar()
    if pos_ck:
        op.drop_constraint(
            "ck_broker_position_snapshot_status",
            "broker_position_snapshot",
            schema="trading",
            type_="check",
        )
        op.create_check_constraint(
            "ck_broker_position_snapshot_status",
            "broker_position_snapshot",
            f"snapshot_status IN ({_NEW_STATUSES})",
            schema="trading",
        )

    # Kill Switch scope_code 길이 — UBA:{id} / PAPER:{id}
    op.alter_column(
        "kill_switch",
        "scope_code",
        schema="operation",
        type_=sa.String(40),
        existing_type=sa.String(30),
        existing_nullable=False,
    )
    op.alter_column(
        "kill_switch_history",
        "scope_code",
        schema="operation",
        type_=sa.String(40),
        existing_type=sa.String(30),
        existing_nullable=False,
    )

    # ORPHAN 3건: UBA 매칭 불가 → RETIRED (물리 삭제 없음)
    op.execute(
        """
        UPDATE trading.broker_account_snapshot
        SET snapshot_status = 'RETIRED',
            raw_data = COALESCE(raw_data, '{}'::jsonb) ||
              jsonb_build_object(
                '_retire',
                jsonb_build_object(
                  'actor', 'SYSTEM_STEP8_5_18',
                  'reason',
                  'Unmatchable ORPHAN: no UserBrokerAccount available'
                )
              )
        WHERE snapshot_status = 'ORPHAN'
          AND user_broker_account_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE trading.broker_position_snapshot
        SET snapshot_status = 'RETIRED'
        WHERE snapshot_status = 'ORPHAN'
          AND user_broker_account_id IS NULL
        """
    )


def downgrade() -> None:
    # 확장 상태를 구 상태로 되돌린 뒤 제약 복구
    op.execute(
        """
        UPDATE trading.broker_account_snapshot
        SET snapshot_status = 'ORPHAN'
        WHERE snapshot_status IN (
            'REBIND_PENDING', 'REBOUND', 'RETIRED', 'PURGED'
        )
        """
    )
    op.execute(
        """
        UPDATE trading.broker_position_snapshot
        SET snapshot_status = 'ORPHAN'
        WHERE snapshot_status IN (
            'REBIND_PENDING', 'REBOUND', 'RETIRED', 'PURGED'
        )
        """
    )

    op.drop_constraint(
        "ck_broker_account_snapshot_status",
        "broker_account_snapshot",
        schema="trading",
        type_="check",
    )
    op.create_check_constraint(
        "ck_broker_account_snapshot_status",
        "broker_account_snapshot",
        f"snapshot_status IN ({_OLD_STATUSES})",
        schema="trading",
    )

    bind = op.get_bind()
    pos_ck = bind.execute(
        sa.text(
            """
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_broker_position_snapshot_status'
            """
        )
    ).scalar()
    if pos_ck:
        op.drop_constraint(
            "ck_broker_position_snapshot_status",
            "broker_position_snapshot",
            schema="trading",
            type_="check",
        )
        op.create_check_constraint(
            "ck_broker_position_snapshot_status",
            "broker_position_snapshot",
            f"snapshot_status IN ({_OLD_STATUSES})",
            schema="trading",
        )

    op.alter_column(
        "kill_switch",
        "scope_code",
        schema="operation",
        type_=sa.String(30),
        existing_type=sa.String(40),
        existing_nullable=False,
    )
    op.alter_column(
        "kill_switch_history",
        "scope_code",
        schema="operation",
        type_=sa.String(30),
        existing_type=sa.String(40),
        existing_nullable=False,
    )
