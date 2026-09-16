"""AI Candidate Assessment (STEP 11-9).

Revision ID: aa1b2c3d4e5f
Revises: z6a7b8c9d0e1
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "aa1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "z6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ASSESSMENT_STATUS = (
    "'DRAFT','QUEUED','RUNNING','VALIDATED','VALIDATED_WITH_WARNINGS',"
    "'BLOCKED','INVALID','FAILED','CANCELLED','REVIEW_PENDING',"
    "'REVIEW_APPROVED','REVIEW_REJECTED','SUPERSEDED','ARCHIVED'"
)

_EVIDENCE_TYPES = (
    "'NEWS','DISCLOSURE','CHART','MARKET','REVIEW','FUNDAMENTAL','OTHER'"
)

_DIRECTIONS = "'POSITIVE','NEGATIVE','NEUTRAL','UNCERTAIN'"

_CONFLICT_STATUS = (
    "'NO_CONFLICT','MINOR_CONFLICT','MAJOR_CONFLICT','INSUFFICIENT_EVIDENCE'"
)

_TEMPORAL_STATUS = (
    "'ALIGNED','ACCEPTABLE','STALE','CONFLICTED','UNKNOWN'"
)

_SCORE_0_100 = (
    "({col} IS NULL OR ({col} >= 0 AND {col} <= 100))"
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")

    op.create_table(
        "candidate_assessment",
        sa.Column(
            "assessment_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("assessment_key", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("assessment_type", sa.String(20), nullable=False),
        sa.Column("market_type", sa.String(40), nullable=False),
        sa.Column("exchange_code", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("instrument_id", sa.BigInteger()),
        sa.Column("instrument_key", sa.String(64)),
        sa.Column("task_type", sa.String(60), nullable=False),
        sa.Column(
            "assessment_status",
            sa.String(40),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "execution_mode",
            sa.String(20),
            nullable=False,
            server_default="MOCK",
        ),
        sa.Column(
            "data_classification",
            sa.String(40),
            nullable=False,
            server_default="PUBLIC_DERIVED",
        ),
        sa.Column("execution_request_id", sa.BigInteger()),
        sa.Column("execution_result_id", sa.BigInteger()),
        sa.Column("prompt_template_id", sa.BigInteger()),
        sa.Column("prompt_version_id", sa.BigInteger()),
        sa.Column("output_schema_id", sa.BigInteger()),
        sa.Column("policy_ids", postgresql.JSONB()),
        sa.Column("provider_code", sa.String(40)),
        sa.Column("model", sa.String(200)),
        sa.Column("evidence_bundle_hash", sa.String(64)),
        sa.Column("source_version_hash", sa.String(64)),
        sa.Column("input_hash", sa.String(64)),
        sa.Column("result_hash", sa.String(64)),
        sa.Column("analytical_score", sa.Float()),
        sa.Column("risk_score", sa.Float()),
        sa.Column("overall_score", sa.Float()),
        sa.Column("confidence", sa.Float()),
        sa.Column("evidence_quality", sa.String(40)),
        sa.Column("data_quality", sa.String(40)),
        sa.Column("conflict_status", sa.String(40)),
        sa.Column("temporal_alignment_status", sa.String(40)),
        sa.Column("review_decision", sa.String(40)),
        sa.Column("safe_result", postgresql.JSONB()),
        sa.Column("warnings", postgresql.JSONB()),
        sa.Column(
            "source_missing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("assessed_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_by_id", sa.BigInteger()),
        sa.Column(
            "lock_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
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
            "assessment_type IN ('STOCK', 'CRYPTO')",
            name="ck_ai_cand_assessment_type",
        ),
        sa.CheckConstraint(
            f"assessment_status IN ({_ASSESSMENT_STATUS})",
            name="ck_ai_cand_assessment_status",
        ),
        sa.CheckConstraint(
            "execution_mode IN ('DRY_RUN', 'MOCK', 'EXTERNAL')",
            name="ck_ai_cand_assessment_exec_mode",
        ),
        sa.CheckConstraint(
            "data_classification IN "
            "('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED','PUBLIC_DERIVED')",
            name="ck_ai_cand_assessment_classification",
        ),
        sa.CheckConstraint(
            _SCORE_0_100.format(col="overall_score"),
            name="ck_ai_cand_assessment_overall_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_100.format(col="analytical_score"),
            name="ck_ai_cand_assessment_analytical_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_100.format(col="risk_score"),
            name="ck_ai_cand_assessment_risk_score",
        ),
        sa.CheckConstraint(
            "(confidence IS NULL OR (confidence >= 0 AND confidence <= 1))",
            name="ck_ai_cand_assessment_confidence",
        ),
        sa.CheckConstraint(
            f"(conflict_status IS NULL OR conflict_status IN ({_CONFLICT_STATUS}))",
            name="ck_ai_cand_assessment_conflict_status",
        ),
        sa.CheckConstraint(
            "(temporal_alignment_status IS NULL OR "
            f"temporal_alignment_status IN ({_TEMPORAL_STATUS}))",
            name="ck_ai_cand_assessment_temporal_status",
        ),
        sa.ForeignKeyConstraint(
            ["execution_request_id"],
            ["ai.execution_request.execution_request_id"],
            name="fk_ai_candidate_assessment_exec_request",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "assessment_key", name="uq_ai_candidate_assessment_key"
        ),
        sa.UniqueConstraint(
            "created_by",
            "idempotency_key",
            name="uq_ai_candidate_assessment_idempotency",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_assessment_market_exchange_symbol",
        "candidate_assessment",
        ["market_type", "exchange_code", "symbol"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_assessment_status",
        "candidate_assessment",
        ["assessment_status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_assessment_assessed_at",
        "candidate_assessment",
        ["assessed_at"],
        schema="ai",
    )

    op.create_table(
        "candidate_assessment_evidence",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("candidate_assessment_id", sa.BigInteger(), nullable=False),
        sa.Column("evidence_type", sa.String(40), nullable=False),
        sa.Column("source_analysis_type", sa.String(40), nullable=False),
        sa.Column("document_analysis_id", sa.BigInteger()),
        sa.Column("market_analysis_id", sa.BigInteger()),
        sa.Column("review_decision_id", sa.BigInteger()),
        sa.Column("source_version", sa.String(40)),
        sa.Column("evidence_hash", sa.String(64)),
        sa.Column("quality_status", sa.String(40)),
        sa.Column("direction", sa.String(20)),
        sa.Column("temporal_status", sa.String(40)),
        sa.Column("summary_sanitized", sa.String(2000)),
        sa.Column(
            "included",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("exclusion_reason", sa.String(500)),
        sa.Column("analyzed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"evidence_type IN ({_EVIDENCE_TYPES})",
            name="ck_ai_cand_evidence_type",
        ),
        sa.CheckConstraint(
            f"(direction IS NULL OR direction IN ({_DIRECTIONS}))",
            name="ck_ai_cand_evidence_direction",
        ),
        sa.CheckConstraint(
            f"(temporal_status IS NULL OR temporal_status IN ({_TEMPORAL_STATUS}))",
            name="ck_ai_cand_evidence_temporal_status",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_assessment_id"],
            ["ai.candidate_assessment.assessment_id"],
            name="fk_ai_cand_evidence_assessment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_analysis_id"],
            ["ai.document_analysis.document_analysis_id"],
            name="fk_ai_cand_evidence_doc_analysis",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["market_analysis_id"],
            ["ai.market_analysis.market_analysis_id"],
            name="fk_ai_cand_evidence_mkt_analysis",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["review_decision_id"],
            ["ai.analysis_review_decision.decision_id"],
            name="fk_ai_cand_evidence_review_decision",
            ondelete="SET NULL",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_evidence_assessment",
        "candidate_assessment_evidence",
        ["candidate_assessment_id"],
        schema="ai",
    )

    op.create_table(
        "candidate_assessment_factor",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("candidate_assessment_id", sa.BigInteger(), nullable=False),
        sa.Column("factor_type", sa.String(40), nullable=False),
        sa.Column("factor_code", sa.String(80), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("importance", sa.Float()),
        sa.Column("confidence", sa.Float()),
        sa.Column("evidence_summary", sa.String(1000)),
        sa.Column("citation_reference", sa.String(200)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"direction IN ({_DIRECTIONS})",
            name="ck_ai_cand_factor_direction",
        ),
        sa.CheckConstraint(
            _SCORE_0_100.format(col="importance"),
            name="ck_ai_cand_factor_importance",
        ),
        sa.CheckConstraint(
            "(confidence IS NULL OR (confidence >= 0 AND confidence <= 1))",
            name="ck_ai_cand_factor_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_assessment_id"],
            ["ai.candidate_assessment.assessment_id"],
            name="fk_ai_cand_factor_assessment",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_factor_assessment",
        "candidate_assessment_factor",
        ["candidate_assessment_id"],
        schema="ai",
    )

    op.create_table(
        "candidate_assessment_risk",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("candidate_assessment_id", sa.BigInteger(), nullable=False),
        sa.Column("risk_type", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("evidence_summary", sa.String(1000)),
        sa.Column("citation_reference", sa.String(200)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_ai_cand_risk_severity",
        ),
        sa.CheckConstraint(
            "(confidence IS NULL OR (confidence >= 0 AND confidence <= 1))",
            name="ck_ai_cand_risk_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_assessment_id"],
            ["ai.candidate_assessment.assessment_id"],
            name="fk_ai_cand_risk_assessment",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_risk_assessment",
        "candidate_assessment_risk",
        ["candidate_assessment_id"],
        schema="ai",
    )

    op.create_table(
        "candidate_assessment_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("candidate_assessment_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("previous_status", sa.String(40)),
        sa.Column("new_status", sa.String(40)),
        sa.Column("reason", sa.String(500)),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("detail_sanitized", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["candidate_assessment_id"],
            ["ai.candidate_assessment.assessment_id"],
            name="fk_ai_cand_hist_assessment",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_hist_assessment",
        "candidate_assessment_history",
        ["candidate_assessment_id"],
        schema="ai",
    )

    # Review source_type에 CANDIDATE_ASSESSMENT 허용
    op.drop_constraint(
        "ck_ai_review_assignment_source_type",
        "analysis_review_assignment",
        schema="ai",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_review_assignment_source_type",
        "analysis_review_assignment",
        "analysis_source_type IN "
        "('NEWS','DISCLOSURE','CHART','MARKET','EXECUTION',"
        "'CANDIDATE_ASSESSMENT')",
        schema="ai",
    )
    op.drop_constraint(
        "ck_ai_review_decision_source_type",
        "analysis_review_decision",
        schema="ai",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_review_decision_source_type",
        "analysis_review_decision",
        "analysis_source_type IN "
        "('NEWS','DISCLOSURE','CHART','MARKET','EXECUTION',"
        "'CANDIDATE_ASSESSMENT')",
        schema="ai",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ai_review_assignment_source_type",
        "analysis_review_assignment",
        schema="ai",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_review_assignment_source_type",
        "analysis_review_assignment",
        "analysis_source_type IN "
        "('NEWS','DISCLOSURE','CHART','MARKET','EXECUTION')",
        schema="ai",
    )
    op.drop_constraint(
        "ck_ai_review_decision_source_type",
        "analysis_review_decision",
        schema="ai",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_review_decision_source_type",
        "analysis_review_decision",
        "analysis_source_type IN "
        "('NEWS','DISCLOSURE','CHART','MARKET','EXECUTION')",
        schema="ai",
    )

    op.drop_index(
        "ix_ai_cand_hist_assessment",
        table_name="candidate_assessment_history",
        schema="ai",
    )
    op.drop_table("candidate_assessment_history", schema="ai")

    op.drop_index(
        "ix_ai_cand_risk_assessment",
        table_name="candidate_assessment_risk",
        schema="ai",
    )
    op.drop_table("candidate_assessment_risk", schema="ai")

    op.drop_index(
        "ix_ai_cand_factor_assessment",
        table_name="candidate_assessment_factor",
        schema="ai",
    )
    op.drop_table("candidate_assessment_factor", schema="ai")

    op.drop_index(
        "ix_ai_cand_evidence_assessment",
        table_name="candidate_assessment_evidence",
        schema="ai",
    )
    op.drop_table("candidate_assessment_evidence", schema="ai")

    op.drop_index(
        "ix_ai_cand_assessment_assessed_at",
        table_name="candidate_assessment",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_assessment_status",
        table_name="candidate_assessment",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_assessment_market_exchange_symbol",
        table_name="candidate_assessment",
        schema="ai",
    )
    op.drop_table("candidate_assessment", schema="ai")
