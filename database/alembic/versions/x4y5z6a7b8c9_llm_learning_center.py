"""LLM Learning Center — user comments + assistant conversation (research only).

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "x4y5z6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "w3x4y5z6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_learning_user_comment",
        sa.Column("comment_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=True),
        sa.Column("related_analysis_id", sa.BigInteger(), nullable=True),
        sa.Column("related_prediction_id", sa.BigInteger(), nullable=True),
        sa.Column("related_shadow_id", sa.BigInteger(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column(
            "review_status",
            sa.String(32),
            nullable=False,
            server_default="USER_REVIEWED",
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="operation",
    )
    op.create_index(
        "ix_llm_learning_comment_market_created",
        "llm_learning_user_comment",
        ["market", "created_at"],
        schema="operation",
    )

    op.create_table(
        "llm_learning_assistant_message",
        sa.Column("message_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("market_scope", sa.String(20), nullable=True),
        sa.Column("intent", sa.String(64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_json", postgresql.JSONB(), nullable=False),
        sa.Column("context_refs_json", postgresql.JSONB(), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="operation",
    )
    op.create_index(
        "ix_llm_learning_assistant_created",
        "llm_learning_assistant_message",
        ["created_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_llm_learning_assistant_created",
        table_name="llm_learning_assistant_message",
        schema="operation",
    )
    op.drop_table("llm_learning_assistant_message", schema="operation")
    op.drop_index(
        "ix_llm_learning_comment_market_created",
        table_name="llm_learning_user_comment",
        schema="operation",
    )
    op.drop_table("llm_learning_user_comment", schema="operation")
