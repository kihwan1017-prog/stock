"""STEP 10-2 — operation.runtime_control_state (Scheduler desired 영속화).

Revision ID: t0a1b2c3d4e5
Revises: s8c9d0e1f2a3
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "t0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "s8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COMPONENT_TRADING_SCHEDULER = "TRADING_SCHEDULER"
SCOPE_GLOBAL = "GLOBAL"


def upgrade() -> None:
    op.create_table(
        "runtime_control_state",
        sa.Column(
            "control_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column(
            "scope_type",
            sa.String(32),
            nullable=False,
            server_default=SCOPE_GLOBAL,
        ),
        sa.Column(
            "scope_id",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("desired_state", sa.String(32), nullable=False),
        sa.Column("last_actual_state", sa.String(32), nullable=True),
        sa.Column("requested_by", sa.String(128), nullable=True),
        sa.Column("requested_reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("blocked_reason", sa.String(256), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "startup_restore_attempted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("startup_restore_result", sa.String(64), nullable=True),
        sa.Column("process_instance_id", sa.String(128), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "component",
            "scope_type",
            "scope_id",
            name="uq_runtime_control_state_scope",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_runtime_control_state_component",
        "runtime_control_state",
        ["component"],
        schema="operation",
    )

    op.execute(
        sa.text(
            """
            INSERT INTO operation.runtime_control_state (
                component,
                scope_type,
                scope_id,
                desired_state,
                last_actual_state,
                requested_by,
                requested_reason,
                detail
            ) VALUES (
                :component,
                :scope_type,
                0,
                'PAUSE',
                'PAUSED',
                'migration',
                'STEP 10-2 initial seed',
                '{}'::jsonb
            )
            """
        ).bindparams(
            component=COMPONENT_TRADING_SCHEDULER,
            scope_type=SCOPE_GLOBAL,
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_control_state_component",
        table_name="runtime_control_state",
        schema="operation",
    )
    op.drop_table("runtime_control_state", schema="operation")
