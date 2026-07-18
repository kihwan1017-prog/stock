"""enrich ai analysis run for reproducibility and metrics

Revision ID: f1a9e8b7c6d5
Revises: e6c2d93f5b12
Create Date: 2026-07-18 09:00:00.000000

STEP37-07:
- AI 분석 run append-only (source+model unique 제거)
- prompt_version / context_hash / fallback / latency 저장
- 후보별 rationale JSON, 재실행 parent 연결
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f1a9e8b7c6d5"
down_revision: Union[str, Sequence[str], None] = "e6c2d93f5b12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_candidate_analysis_run_source_model",
        "candidate_analysis_run",
        schema="ai",
        type_="unique",
    )

    op.add_column(
        "candidate_analysis_run",
        sa.Column(
            "prompt_version",
            sa.String(length=50),
            server_default=sa.text("'ranker-v2'"),
            nullable=False,
        ),
        schema="ai",
    )
    op.add_column(
        "candidate_analysis_run",
        sa.Column("context_hash", sa.String(length=64), nullable=True),
        schema="ai",
    )
    op.add_column(
        "candidate_analysis_run",
        sa.Column(
            "used_fallback",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        schema="ai",
    )
    op.add_column(
        "candidate_analysis_run",
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "candidate_analysis_run",
        sa.Column(
            "error_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        schema="ai",
    )
    op.add_column(
        "candidate_analysis_run",
        sa.Column(
            "request_count",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        schema="ai",
    )
    op.add_column(
        "candidate_analysis_run",
        sa.Column("parent_analysis_run_id", sa.BigInteger(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "candidate_analysis_run",
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema="ai",
    )
    op.create_foreign_key(
        "fk_candidate_analysis_run_parent",
        "candidate_analysis_run",
        "candidate_analysis_run",
        ["parent_analysis_run_id"],
        ["analysis_run_id"],
        source_schema="ai",
        referent_schema="ai",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_candidate_analysis_run_exchange_created",
        "candidate_analysis_run",
        ["exchange_code", "created_at"],
        schema="ai",
    )
    op.create_index(
        "ix_candidate_analysis_run_context_hash",
        "candidate_analysis_run",
        ["context_hash"],
        schema="ai",
    )

    op.add_column(
        "candidate_analysis_result",
        sa.Column(
            "rationale",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema="ai",
    )


def downgrade() -> None:
    op.drop_column("candidate_analysis_result", "rationale", schema="ai")

    op.drop_index(
        "ix_candidate_analysis_run_context_hash",
        table_name="candidate_analysis_run",
        schema="ai",
    )
    op.drop_index(
        "ix_candidate_analysis_run_exchange_created",
        table_name="candidate_analysis_run",
        schema="ai",
    )
    op.drop_constraint(
        "fk_candidate_analysis_run_parent",
        "candidate_analysis_run",
        schema="ai",
        type_="foreignkey",
    )
    op.drop_column(
        "candidate_analysis_run", "metrics", schema="ai"
    )
    op.drop_column(
        "candidate_analysis_run",
        "parent_analysis_run_id",
        schema="ai",
    )
    op.drop_column(
        "candidate_analysis_run", "request_count", schema="ai"
    )
    op.drop_column(
        "candidate_analysis_run", "error_count", schema="ai"
    )
    op.drop_column(
        "candidate_analysis_run", "duration_ms", schema="ai"
    )
    op.drop_column(
        "candidate_analysis_run", "used_fallback", schema="ai"
    )
    op.drop_column(
        "candidate_analysis_run", "context_hash", schema="ai"
    )
    op.drop_column(
        "candidate_analysis_run", "prompt_version", schema="ai"
    )
    op.create_unique_constraint(
        "uq_candidate_analysis_run_source_model",
        "candidate_analysis_run",
        ["source_candidate_run_id", "model_name"],
        schema="ai",
    )
