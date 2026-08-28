"""AI development work history — Cursor/GPT 작업 이력 영구 저장.

Revision ID: dw1a2b3c4d5e
Revises: cm1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "dw1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "cm1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_development_work_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("work_id", sa.String(128), nullable=False),
        sa.Column("parent_work_id", sa.String(128), nullable=True),
        sa.Column("project_code", sa.String(64), nullable=False),
        sa.Column("work_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("request_source", sa.String(32), nullable=True),
        sa.Column("executor", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("command_text", sa.Text(), nullable=True),
        sa.Column("scope_json", postgresql.JSONB(), nullable=True),
        sa.Column("safety_constraints_json", postgresql.JSONB(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("final_verdict", sa.String(128), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("base_commit", sa.String(64), nullable=True),
        sa.Column("result_commit", sa.String(64), nullable=True),
        sa.Column("changed_files_json", postgresql.JSONB(), nullable=True),
        sa.Column("tests_json", postgresql.JSONB(), nullable=True),
        sa.Column("deployment_json", postgresql.JSONB(), nullable=True),
        sa.Column("safety_result_json", postgresql.JSONB(), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(), nullable=True),
        sa.Column("remaining_issues_json", postgresql.JSONB(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("command_hash", sa.String(64), nullable=True),
        sa.Column("dedupe_key", sa.String(256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("work_id", name="uq_ai_development_work_history_work_id"),
        schema="operation",
    )
    op.create_index(
        "ix_ai_dev_work_history_project_created",
        "ai_development_work_history",
        ["project_code", sa.text("created_at DESC")],
        schema="operation",
    )
    op.create_index(
        "ix_ai_dev_work_history_status",
        "ai_development_work_history",
        ["status"],
        schema="operation",
    )
    op.create_index(
        "ix_ai_dev_work_history_work_type",
        "ai_development_work_history",
        ["work_type"],
        schema="operation",
    )
    op.create_index(
        "ix_ai_dev_work_history_parent",
        "ai_development_work_history",
        ["parent_work_id"],
        schema="operation",
    )
    op.create_index(
        "ix_ai_dev_work_history_result_commit",
        "ai_development_work_history",
        ["result_commit"],
        schema="operation",
    )
    op.create_index(
        "ix_ai_dev_work_history_dedupe_key",
        "ai_development_work_history",
        ["dedupe_key"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_dev_work_history_dedupe_key",
        table_name="ai_development_work_history",
        schema="operation",
    )
    op.drop_index(
        "ix_ai_dev_work_history_result_commit",
        table_name="ai_development_work_history",
        schema="operation",
    )
    op.drop_index(
        "ix_ai_dev_work_history_parent",
        table_name="ai_development_work_history",
        schema="operation",
    )
    op.drop_index(
        "ix_ai_dev_work_history_work_type",
        table_name="ai_development_work_history",
        schema="operation",
    )
    op.drop_index(
        "ix_ai_dev_work_history_status",
        table_name="ai_development_work_history",
        schema="operation",
    )
    op.drop_index(
        "ix_ai_dev_work_history_project_created",
        table_name="ai_development_work_history",
        schema="operation",
    )
    op.drop_table("ai_development_work_history", schema="operation")
