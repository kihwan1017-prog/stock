"""AI Review / Dataset / Benchmark (STEP 11-8).

Revision ID: z6a7b8c9d0e1
Revises: y5f6a7b8c9d0
"""

from __future__ import annotations

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "z6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "y5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCORE_0_5 = (
    "({col} IS NULL OR ({col} >= 0 AND {col} <= 5))"
)

AI_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("AI_REVIEW_VIEW", "AI 리뷰 조회"),
    ("AI_REVIEW_ASSIGN", "AI 리뷰 배정"),
    ("AI_REVIEW_SUBMIT", "AI 리뷰 제출"),
    ("AI_REVIEW_DECIDE", "AI 리뷰 승인 결정"),
    ("AI_DATASET_MANAGE", "AI 평가 데이터셋 관리"),
    ("AI_BENCHMARK_RUN", "AI 벤치마크 실행"),
    ("AI_BENCHMARK_VIEW", "AI 벤치마크 조회"),
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")

    op.create_table(
        "analysis_review_assignment",
        sa.Column(
            "assignment_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("analysis_source_type", sa.String(40), nullable=False),
        sa.Column("source_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("document_analysis_id", sa.BigInteger()),
        sa.Column("market_analysis_id", sa.BigInteger()),
        sa.Column("execution_result_id", sa.BigInteger()),
        sa.Column("assigned_reviewer_id", sa.String(100)),
        sa.Column("assigned_by", sa.String(100), nullable=False),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default="UNASSIGNED",
        ),
        sa.Column(
            "priority",
            sa.String(20),
            nullable=False,
            server_default="NORMAL",
        ),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "lock_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "reason",
            sa.String(500),
            nullable=False,
            server_default="",
        ),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "analysis_source_type IN "
            "('NEWS','DISCLOSURE','CHART','MARKET','EXECUTION')",
            name="ck_ai_review_assignment_source_type",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'UNASSIGNED','ASSIGNED','IN_REVIEW','COMPLETED',"
            "'CANCELLED','EXPIRED')",
            name="ck_ai_review_assignment_status",
        ),
        sa.CheckConstraint(
            "priority IN ('NORMAL','HIGH','LOW','URGENT')",
            name="ck_ai_review_assignment_priority",
        ),
        sa.CheckConstraint(
            "("
            "(CASE WHEN document_analysis_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN market_analysis_id IS NOT NULL THEN 1 ELSE 0 END)"
            ") <= 1",
            name="ck_ai_review_assignment_source_ref",
        ),
        sa.ForeignKeyConstraint(
            ["document_analysis_id"],
            ["ai.document_analysis.document_analysis_id"],
            name="fk_ai_review_assignment_document",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["market_analysis_id"],
            ["ai.market_analysis.market_analysis_id"],
            name="fk_ai_review_assignment_market",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["execution_result_id"],
            ["ai.execution_result.execution_result_id"],
            name="fk_ai_review_assignment_exec_result",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "analysis_source_type",
            "source_analysis_id",
            "assigned_reviewer_id",
            name="uq_ai_review_assignment_source_reviewer",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_review_assignment_status",
        "analysis_review_assignment",
        ["status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_review_assignment_source",
        "analysis_review_assignment",
        ["analysis_source_type", "source_analysis_id"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_review_assignment_reviewer",
        "analysis_review_assignment",
        ["assigned_reviewer_id"],
        schema="ai",
    )

    op.create_table(
        "analysis_review",
        sa.Column(
            "review_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("assignment_id", sa.BigInteger(), nullable=False),
        sa.Column("reviewer_id", sa.String(100), nullable=False),
        sa.Column(
            "review_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "decision",
            sa.String(40),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("overall_score", sa.Float()),
        sa.Column("correctness_score", sa.Float()),
        sa.Column("relevance_score", sa.Float()),
        sa.Column("completeness_score", sa.Float()),
        sa.Column("citation_score", sa.Float()),
        sa.Column("safety_score", sa.Float()),
        sa.Column("clarity_score", sa.Float()),
        sa.Column("calibration_score", sa.Float()),
        sa.Column("data_quality_score", sa.Float()),
        sa.Column("reviewer_confidence", sa.Float()),
        sa.Column("findings_summary", sa.Text()),
        sa.Column("correction_summary", sa.Text()),
        sa.Column("revision_request", sa.Text()),
        sa.Column(
            "reason",
            sa.String(500),
            nullable=False,
            server_default="",
        ),
        sa.Column("amendment_reason", sa.String(500)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("amended_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','SUBMITTED','AMENDED','WITHDRAWN')",
            name="ck_ai_analysis_review_status",
        ),
        sa.CheckConstraint(
            "decision IN ("
            "'PENDING','APPROVED','APPROVED_WITH_WARNINGS',"
            "'REVISION_REQUESTED','REJECTED','NOT_REVIEWABLE')",
            name="ck_ai_analysis_review_decision",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="overall_score"),
            name="ck_ai_analysis_review_overall_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="correctness_score"),
            name="ck_ai_analysis_review_correctness_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="relevance_score"),
            name="ck_ai_analysis_review_relevance_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="completeness_score"),
            name="ck_ai_analysis_review_completeness_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="citation_score"),
            name="ck_ai_analysis_review_citation_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="safety_score"),
            name="ck_ai_analysis_review_safety_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="clarity_score"),
            name="ck_ai_analysis_review_clarity_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="calibration_score"),
            name="ck_ai_analysis_review_calibration_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="data_quality_score"),
            name="ck_ai_analysis_review_data_quality_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="reviewer_confidence"),
            name="ck_ai_analysis_review_reviewer_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["ai.analysis_review_assignment.assignment_id"],
            name="fk_ai_review_assignment",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "assignment_id",
            "reviewer_id",
            "review_version",
            name="uq_ai_analysis_review_version",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_analysis_review_status",
        "analysis_review",
        ["status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_analysis_review_reviewer",
        "analysis_review",
        ["reviewer_id"],
        schema="ai",
    )

    op.create_table(
        "analysis_review_finding",
        sa.Column(
            "finding_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("review_id", sa.BigInteger(), nullable=False),
        sa.Column("finding_type", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("field_path", sa.String(200)),
        sa.Column("finding_code", sa.String(80)),
        sa.Column(
            "description_sanitized",
            sa.String(1000),
            nullable=False,
        ),
        sa.Column("suggested_correction", sa.String(1000)),
        sa.Column("evidence_reference", sa.String(200)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "finding_type IN ("
            "'FACTUAL_ERROR','UNSUPPORTED_CLAIM','CITATION_MISSING',"
            "'CITATION_MISMATCH','NUMERIC_MISMATCH','SYMBOL_MISMATCH',"
            "'ENTITY_MISMATCH','TIMEFRAME_MISMATCH',"
            "'SOURCE_VERSION_MISMATCH','OVERCONFIDENT','UNDERCONFIDENT',"
            "'SCHEMA_WEAKNESS','PROMPT_WEAKNESS','POLICY_WARNING',"
            "'SAFETY_VIOLATION','DATA_QUALITY_IGNORED',"
            "'IMPORTANT_FACT_OMITTED','HALLUCINATION','OTHER')",
            name="ck_ai_review_finding_type",
        ),
        sa.CheckConstraint(
            "severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_ai_review_finding_severity",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["ai.analysis_review.review_id"],
            name="fk_ai_review_finding",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_review_finding_review",
        "analysis_review_finding",
        ["review_id"],
        schema="ai",
    )

    op.create_table(
        "analysis_review_decision",
        sa.Column(
            "decision_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("analysis_source_type", sa.String(40), nullable=False),
        sa.Column("source_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "decision",
            sa.String(40),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "decision_rule",
            sa.String(80),
            nullable=False,
            server_default="AUTO",
        ),
        sa.Column(
            "consensus_status",
            sa.String(40),
            nullable=False,
            server_default="INSUFFICIENT_REVIEWS",
        ),
        sa.Column(
            "reviewer_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "approved_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "rejected_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "warning_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("average_overall_score", sa.Float()),
        sa.Column(
            "critical_finding_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("decided_by", sa.String(100)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("override_reason", sa.String(500)),
        sa.Column(
            "lock_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "analysis_source_type IN "
            "('NEWS','DISCLOSURE','CHART','MARKET','EXECUTION')",
            name="ck_ai_review_decision_source_type",
        ),
        sa.CheckConstraint(
            "decision IN ("
            "'PENDING','APPROVED','APPROVED_WITH_WARNINGS',"
            "'REVISION_REQUESTED','REJECTED','NOT_REVIEWABLE')",
            name="ck_ai_review_decision_decision",
        ),
        sa.CheckConstraint(
            "consensus_status IN ("
            "'CONSENSUS','MINOR_DISAGREEMENT','MAJOR_DISAGREEMENT',"
            "'MANAGER_REVIEW_REQUIRED','INSUFFICIENT_REVIEWS')",
            name="ck_ai_review_decision_consensus",
        ),
        sa.CheckConstraint(
            "decision_rule IN ("
            "'AUTO','CORE_SAFETY_CRITICAL','MAJOR_DISAGREEMENT',"
            "'MAJORITY_REJECT','REVISION_REQUESTED','AUTO_THRESHOLD',"
            "'AWAITING_THRESHOLD','MANAGER_OVERRIDE')",
            name="ck_ai_review_decision_rule",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="average_overall_score"),
            name="ck_ai_review_decision_avg_score",
        ),
        sa.UniqueConstraint(
            "analysis_source_type",
            "source_analysis_id",
            name="uq_ai_review_decision_source",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_review_decision_source",
        "analysis_review_decision",
        ["analysis_source_type", "source_analysis_id"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_review_decision_status",
        "analysis_review_decision",
        ["decision"],
        schema="ai",
    )

    op.create_table(
        "evaluation_dataset",
        sa.Column(
            "dataset_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("task_type", sa.String(60), nullable=False),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "dataset_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "source_policy",
            sa.String(80),
            nullable=False,
            server_default="REFERENCE_ONLY",
        ),
        sa.Column("checksum", sa.String(64)),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','VALIDATED','ACTIVE','ARCHIVED')",
            name="ck_ai_eval_dataset_status",
        ),
        sa.UniqueConstraint(
            "code",
            "dataset_version",
            name="uq_ai_eval_dataset_code_version",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_eval_dataset_status",
        "evaluation_dataset",
        ["status"],
        schema="ai",
    )

    op.create_table(
        "evaluation_dataset_item",
        sa.Column(
            "item_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("source_analysis_id", sa.BigInteger()),
        sa.Column("source_document_key", sa.String(200)),
        sa.Column("snapshot_key", sa.String(200)),
        sa.Column(
            "input_reference_hash",
            sa.String(64),
            nullable=False,
        ),
        sa.Column("expected_result", postgresql.JSONB()),
        sa.Column("expected_schema_version", sa.String(20)),
        sa.Column("grading_rubric", postgresql.JSONB()),
        sa.Column(
            "data_classification",
            sa.String(40),
            nullable=False,
            server_default="PUBLIC",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "data_classification IN "
            "('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')",
            name="ck_ai_eval_item_classification",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','INACTIVE')",
            name="ck_ai_eval_item_status",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["ai.evaluation_dataset.dataset_id"],
            name="fk_ai_eval_item_dataset",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "input_reference_hash",
            name="uq_ai_eval_dataset_item_hash",
        ),
        schema="ai",
    )

    op.create_table(
        "benchmark_run",
        sa.Column(
            "benchmark_run_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_configuration_id", sa.BigInteger()),
        sa.Column("provider_code", sa.String(40), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("prompt_template_id", sa.BigInteger()),
        sa.Column("prompt_version_id", sa.BigInteger()),
        sa.Column("output_schema_id", sa.BigInteger()),
        sa.Column("policy_ids", postgresql.JSONB()),
        sa.Column(
            "execution_mode",
            sa.String(20),
            nullable=False,
            server_default="MOCK",
        ),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "item_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "completed_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "failed_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "blocked_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("estimated_cost", sa.Float()),
        sa.Column("metrics", postgresql.JSONB()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "execution_mode IN ('MOCK','EXTERNAL')",
            name="ck_ai_benchmark_run_execution_mode",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'DRAFT','READY','RUNNING','COMPLETED','CANCELLED')",
            name="ck_ai_benchmark_run_status",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["ai.evaluation_dataset.dataset_id"],
            name="fk_ai_benchmark_dataset",
            ondelete="RESTRICT",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_benchmark_run_status",
        "benchmark_run",
        ["status"],
        schema="ai",
    )

    op.create_table(
        "benchmark_result",
        sa.Column(
            "benchmark_result_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("benchmark_run_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_item_id", sa.BigInteger(), nullable=False),
        sa.Column("execution_request_id", sa.BigInteger()),
        sa.Column("score", sa.Float()),
        sa.Column("correctness_score", sa.Float()),
        sa.Column("schema_score", sa.Float()),
        sa.Column("citation_score", sa.Float()),
        sa.Column("safety_score", sa.Float()),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("tokens", sa.Integer()),
        sa.Column("estimated_cost", sa.Float()),
        sa.Column("result_status", sa.String(40), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("detail_sanitized", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "result_status IN ('SUCCEEDED','FAILED','BLOCKED')",
            name="ck_ai_benchmark_result_status",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="score"),
            name="ck_ai_benchmark_result_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="correctness_score"),
            name="ck_ai_benchmark_result_correctness_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="schema_score"),
            name="ck_ai_benchmark_result_schema_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="citation_score"),
            name="ck_ai_benchmark_result_citation_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="safety_score"),
            name="ck_ai_benchmark_result_safety_score",
        ),
        sa.ForeignKeyConstraint(
            ["benchmark_run_id"],
            ["ai.benchmark_run.benchmark_run_id"],
            name="fk_ai_benchmark_result_run",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "benchmark_run_id",
            "dataset_item_id",
            name="uq_ai_benchmark_result_item",
        ),
        schema="ai",
    )

    _seed_permissions(op.get_bind())


def _seed_permissions(conn: Any) -> None:
    for code, name in AI_PERMISSIONS:
        conn.execute(
            sa.text(
                """
                INSERT INTO auth.permission
                    (code, name, category, description)
                VALUES (:code, :name, 'ai', :name)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code, "name": name},
        )

    conn.execute(
        sa.text(
            """
            INSERT INTO auth.role_permission (role_id, permission_id)
            SELECT r.role_id, p.permission_id
            FROM auth.role r
            CROSS JOIN auth.permission p
            WHERE r.code = 'admin'
              AND p.code IN (
                'AI_REVIEW_VIEW',
                'AI_REVIEW_ASSIGN',
                'AI_REVIEW_SUBMIT',
                'AI_REVIEW_DECIDE',
                'AI_DATASET_MANAGE',
                'AI_BENCHMARK_RUN',
                'AI_BENCHMARK_VIEW'
              )
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM auth.role_permission
            WHERE permission_id IN (
                SELECT permission_id FROM auth.permission
                WHERE code IN (
                    'AI_REVIEW_VIEW',
                    'AI_REVIEW_ASSIGN',
                    'AI_REVIEW_SUBMIT',
                    'AI_REVIEW_DECIDE',
                    'AI_DATASET_MANAGE',
                    'AI_BENCHMARK_RUN',
                    'AI_BENCHMARK_VIEW'
                )
            )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM auth.permission
            WHERE code IN (
                'AI_REVIEW_VIEW',
                'AI_REVIEW_ASSIGN',
                'AI_REVIEW_SUBMIT',
                'AI_REVIEW_DECIDE',
                'AI_DATASET_MANAGE',
                'AI_BENCHMARK_RUN',
                'AI_BENCHMARK_VIEW'
            )
            """
        )
    )

    op.drop_table("benchmark_result", schema="ai")
    op.drop_index(
        "ix_ai_benchmark_run_status",
        table_name="benchmark_run",
        schema="ai",
    )
    op.drop_table("benchmark_run", schema="ai")
    op.drop_table("evaluation_dataset_item", schema="ai")
    op.drop_index(
        "ix_ai_eval_dataset_status",
        table_name="evaluation_dataset",
        schema="ai",
    )
    op.drop_table("evaluation_dataset", schema="ai")
    op.drop_index(
        "ix_ai_review_finding_review",
        table_name="analysis_review_finding",
        schema="ai",
    )
    op.drop_table("analysis_review_finding", schema="ai")
    op.drop_index(
        "ix_ai_analysis_review_reviewer",
        table_name="analysis_review",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_analysis_review_status",
        table_name="analysis_review",
        schema="ai",
    )
    op.drop_table("analysis_review", schema="ai")
    op.drop_index(
        "ix_ai_review_decision_status",
        table_name="analysis_review_decision",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_review_decision_source",
        table_name="analysis_review_decision",
        schema="ai",
    )
    op.drop_table("analysis_review_decision", schema="ai")
    op.drop_index(
        "ix_ai_review_assignment_reviewer",
        table_name="analysis_review_assignment",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_review_assignment_source",
        table_name="analysis_review_assignment",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_review_assignment_status",
        table_name="analysis_review_assignment",
        schema="ai",
    )
    op.drop_table("analysis_review_assignment", schema="ai")
