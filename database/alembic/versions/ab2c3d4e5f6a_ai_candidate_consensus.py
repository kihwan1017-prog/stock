"""AI Candidate Consensus (STEP 11-10).

Revision ID: ab2c3d4e5f6a
Revises: aa1b2c3d4e5f
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ab2c3d4e5f6a"
down_revision: Union[str, Sequence[str], None] = "aa1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSENSUS_STATUS = (
    "'DRAFT','INPUT_VALIDATED','CALCULATED','VALIDATED','VALIDATED_WITH_WARNINGS',"
    "'BLOCKED','INVALID','FAILED','CANCELLED','REVIEW_PENDING',"
    "'REVIEW_APPROVED','REVIEW_REJECTED','SUPERSEDED','ARCHIVED'"
)

_CALCULATION_MODES = "'DETERMINISTIC_ONLY','DETERMINISTIC_PLUS_SYNTHESIS'"

_CONSENSUS_TYPES = "'STOCK','CRYPTO'"

_AGREEMENT_LEVELS = (
    "'STRONG_AGREEMENT','MODERATE_AGREEMENT','WEAK_AGREEMENT',"
    "'SPLIT','INSUFFICIENT','UNKNOWN'"
)

_DISAGREEMENT_LEVELS = "'NONE','LOW','MEDIUM','HIGH','CRITICAL'"

_DIRECTIONS = "'POSITIVE','NEGATIVE','NEUTRAL','UNCERTAIN'"

_INDEPENDENCE_STATUS = (
    "'INDEPENDENT','PARTIALLY_DEPENDENT','SAME_PROVIDER_FAMILY',"
    "'DUPLICATE','UNKNOWN'"
)

_CONFLICT_RESOLUTION = (
    "'UNRESOLVED','ACKNOWLEDGED','RESOLVED_BY_RULE','REVIEW_REQUIRED'"
)

_SCORE_0_100 = "({col} IS NULL OR ({col} >= 0 AND {col} <= 100))"

_WEIGHT_0_2 = "({col} IS NULL OR ({col} >= 0 AND {col} <= 2))"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")

    op.create_table(
        "candidate_consensus",
        sa.Column(
            "consensus_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("consensus_key", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("consensus_type", sa.String(20), nullable=False),
        sa.Column("market_type", sa.String(40), nullable=False),
        sa.Column("exchange_code", sa.String(20), nullable=False),
        sa.Column("instrument_id", sa.BigInteger()),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("task_type", sa.String(60), nullable=False),
        sa.Column(
            "consensus_status",
            sa.String(40),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("calculation_mode", sa.String(40), nullable=False),
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
        sa.Column("evidence_bundle_hash", sa.String(64)),
        sa.Column("source_version_hash", sa.String(64)),
        sa.Column(
            "assessment_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "included_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "excluded_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "provider_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "provider_family_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "model_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "deterministic_version",
            sa.String(40),
            nullable=False,
            server_default="det-1.0.0",
        ),
        sa.Column("execution_request_id", sa.BigInteger()),
        sa.Column("execution_result_id", sa.BigInteger()),
        sa.Column("prompt_template_id", sa.BigInteger()),
        sa.Column("prompt_version_id", sa.BigInteger()),
        sa.Column("output_schema_id", sa.BigInteger()),
        sa.Column("policy_ids", postgresql.JSONB()),
        sa.Column("synthesis_provider_code", sa.String(40)),
        sa.Column("synthesis_model", sa.String(200)),
        sa.Column("weighted_analytical_score", sa.Float()),
        sa.Column("weighted_risk_score", sa.Float()),
        sa.Column("weighted_confidence", sa.Float()),
        sa.Column("agreement_level", sa.String(40)),
        sa.Column("disagreement_level", sa.String(40)),
        sa.Column("evidence_consistency", sa.String(40)),
        sa.Column("provider_diversity", sa.String(40)),
        sa.Column("review_decision", sa.String(40)),
        sa.Column("result_hash", sa.String(64)),
        sa.Column("safe_result", postgresql.JSONB()),
        sa.Column("warnings", postgresql.JSONB()),
        sa.Column("calculated_at", sa.DateTime(timezone=True)),
        sa.Column("synthesized_at", sa.DateTime(timezone=True)),
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
            f"consensus_type IN ({_CONSENSUS_TYPES})",
            name="ck_ai_cand_consensus_type",
        ),
        sa.CheckConstraint(
            f"consensus_status IN ({_CONSENSUS_STATUS})",
            name="ck_ai_cand_consensus_status",
        ),
        sa.CheckConstraint(
            f"calculation_mode IN ({_CALCULATION_MODES})",
            name="ck_ai_cand_consensus_calc_mode",
        ),
        sa.CheckConstraint(
            "execution_mode IN ('DRY_RUN', 'MOCK', 'EXTERNAL')",
            name="ck_ai_cand_consensus_exec_mode",
        ),
        sa.CheckConstraint(
            "data_classification IN "
            "('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED','PUBLIC_DERIVED')",
            name="ck_ai_cand_consensus_classification",
        ),
        sa.CheckConstraint(
            f"(agreement_level IS NULL OR agreement_level IN ({_AGREEMENT_LEVELS}))",
            name="ck_ai_cand_consensus_agreement",
        ),
        sa.CheckConstraint(
            f"(disagreement_level IS NULL OR disagreement_level IN ({_DISAGREEMENT_LEVELS}))",
            name="ck_ai_cand_consensus_disagreement",
        ),
        sa.CheckConstraint(
            _SCORE_0_100.format(col="weighted_analytical_score"),
            name="ck_ai_cand_consensus_analytical_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_100.format(col="weighted_risk_score"),
            name="ck_ai_cand_consensus_risk_score",
        ),
        sa.CheckConstraint(
            "(weighted_confidence IS NULL OR "
            "(weighted_confidence >= 0 AND weighted_confidence <= 1))",
            name="ck_ai_cand_consensus_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["execution_request_id"],
            ["ai.execution_request.execution_request_id"],
            name="fk_ai_candidate_consensus_exec_request",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "consensus_key", name="uq_ai_candidate_consensus_key"
        ),
        sa.UniqueConstraint(
            "created_by",
            "idempotency_key",
            name="uq_ai_candidate_consensus_idempotency",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_consensus_status",
        "candidate_consensus",
        ["consensus_status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_consensus_market_exchange_symbol",
        "candidate_consensus",
        ["market_type", "exchange_code", "symbol"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_consensus_calculated_at",
        "candidate_consensus",
        ["calculated_at"],
        schema="ai",
    )

    op.create_table(
        "candidate_consensus_member",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("candidate_consensus_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_assessment_id", sa.BigInteger()),
        sa.Column("provider_code", sa.String(40)),
        sa.Column("provider_family", sa.String(40)),
        sa.Column("model", sa.String(200)),
        sa.Column(
            "included",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("exclusion_reason", sa.String(500)),
        sa.Column("independence_status", sa.String(40)),
        sa.Column("base_weight", sa.Float()),
        sa.Column("review_weight", sa.Float()),
        sa.Column("scorecard_weight", sa.Float()),
        sa.Column("calibration_weight", sa.Float()),
        sa.Column("citation_weight", sa.Float()),
        sa.Column("data_quality_weight", sa.Float()),
        sa.Column("independence_weight", sa.Float()),
        sa.Column("final_weight", sa.Float()),
        sa.Column("analytical_score", sa.Float()),
        sa.Column("risk_score", sa.Float()),
        sa.Column("confidence", sa.Float()),
        sa.Column("review_decision", sa.String(40)),
        sa.Column("evidence_bundle_hash", sa.String(64)),
        sa.Column("result_hash", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"(independence_status IS NULL OR independence_status IN ({_INDEPENDENCE_STATUS}))",
            name="ck_ai_cand_consensus_member_independence",
        ),
        sa.CheckConstraint(
            _WEIGHT_0_2.format(col="base_weight"),
            name="ck_ai_cand_consensus_member_base_weight",
        ),
        sa.CheckConstraint(
            _WEIGHT_0_2.format(col="review_weight"),
            name="ck_ai_cand_consensus_member_review_weight",
        ),
        sa.CheckConstraint(
            _WEIGHT_0_2.format(col="scorecard_weight"),
            name="ck_ai_cand_consensus_member_scorecard_weight",
        ),
        sa.CheckConstraint(
            _WEIGHT_0_2.format(col="calibration_weight"),
            name="ck_ai_cand_consensus_member_calibration_weight",
        ),
        sa.CheckConstraint(
            _WEIGHT_0_2.format(col="citation_weight"),
            name="ck_ai_cand_consensus_member_citation_weight",
        ),
        sa.CheckConstraint(
            _WEIGHT_0_2.format(col="data_quality_weight"),
            name="ck_ai_cand_consensus_member_data_quality_weight",
        ),
        sa.CheckConstraint(
            _WEIGHT_0_2.format(col="independence_weight"),
            name="ck_ai_cand_consensus_member_independence_weight",
        ),
        sa.CheckConstraint(
            _WEIGHT_0_2.format(col="final_weight"),
            name="ck_ai_cand_consensus_member_final_weight",
        ),
        sa.CheckConstraint(
            _SCORE_0_100.format(col="analytical_score"),
            name="ck_ai_cand_consensus_member_analytical_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_100.format(col="risk_score"),
            name="ck_ai_cand_consensus_member_risk_score",
        ),
        sa.CheckConstraint(
            "(confidence IS NULL OR (confidence >= 0 AND confidence <= 1))",
            name="ck_ai_cand_consensus_member_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_consensus_id"],
            ["ai.candidate_consensus.consensus_id"],
            name="fk_ai_cand_consensus_member_consensus",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_assessment_id"],
            ["ai.candidate_assessment.assessment_id"],
            name="fk_ai_cand_consensus_member_assessment",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "candidate_consensus_id",
            "candidate_assessment_id",
            name="uq_ai_cand_consensus_member_assessment",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_consensus_member_consensus",
        "candidate_consensus_member",
        ["candidate_consensus_id"],
        schema="ai",
    )

    op.create_table(
        "candidate_consensus_factor",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("candidate_consensus_id", sa.BigInteger(), nullable=False),
        sa.Column("factor_type", sa.String(40), nullable=False),
        sa.Column("factor_code", sa.String(80), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column(
            "agreement_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "disagreement_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("weighted_support", sa.Float()),
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
            name="ck_ai_cand_consensus_factor_direction",
        ),
        sa.CheckConstraint(
            "(confidence IS NULL OR (confidence >= 0 AND confidence <= 1))",
            name="ck_ai_cand_consensus_factor_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_consensus_id"],
            ["ai.candidate_consensus.consensus_id"],
            name="fk_ai_cand_consensus_factor_consensus",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_consensus_factor_consensus",
        "candidate_consensus_factor",
        ["candidate_consensus_id"],
        schema="ai",
    )

    op.create_table(
        "candidate_consensus_conflict",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("candidate_consensus_id", sa.BigInteger(), nullable=False),
        sa.Column("conflict_type", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("field_path", sa.String(200)),
        sa.Column("assessment_ids", postgresql.JSONB()),
        sa.Column("description_sanitized", sa.String(2000)),
        sa.Column(
            "resolution_status",
            sa.String(40),
            nullable=False,
            server_default="UNRESOLVED",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_ai_cand_consensus_conflict_severity",
        ),
        sa.CheckConstraint(
            f"resolution_status IN ({_CONFLICT_RESOLUTION})",
            name="ck_ai_cand_consensus_conflict_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_consensus_id"],
            ["ai.candidate_consensus.consensus_id"],
            name="fk_ai_cand_consensus_conflict_consensus",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_consensus_conflict_consensus",
        "candidate_consensus_conflict",
        ["candidate_consensus_id"],
        schema="ai",
    )

    op.create_table(
        "candidate_consensus_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("candidate_consensus_id", sa.BigInteger(), nullable=False),
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
            ["candidate_consensus_id"],
            ["ai.candidate_consensus.consensus_id"],
            name="fk_ai_cand_consensus_hist_consensus",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_consensus_hist_consensus",
        "candidate_consensus_history",
        ["candidate_consensus_id"],
        schema="ai",
    )

    # Review source_type에 CANDIDATE_CONSENSUS 허용
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
        "'CANDIDATE_ASSESSMENT','CANDIDATE_CONSENSUS')",
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
        "'CANDIDATE_ASSESSMENT','CANDIDATE_CONSENSUS')",
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

    op.drop_index(
        "ix_ai_cand_consensus_hist_consensus",
        table_name="candidate_consensus_history",
        schema="ai",
    )
    op.drop_table("candidate_consensus_history", schema="ai")

    op.drop_index(
        "ix_ai_cand_consensus_conflict_consensus",
        table_name="candidate_consensus_conflict",
        schema="ai",
    )
    op.drop_table("candidate_consensus_conflict", schema="ai")

    op.drop_index(
        "ix_ai_cand_consensus_factor_consensus",
        table_name="candidate_consensus_factor",
        schema="ai",
    )
    op.drop_table("candidate_consensus_factor", schema="ai")

    op.drop_index(
        "ix_ai_cand_consensus_member_consensus",
        table_name="candidate_consensus_member",
        schema="ai",
    )
    op.drop_table("candidate_consensus_member", schema="ai")

    op.drop_index(
        "ix_ai_cand_consensus_calculated_at",
        table_name="candidate_consensus",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_consensus_market_exchange_symbol",
        table_name="candidate_consensus",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_consensus_status",
        table_name="candidate_consensus",
        schema="ai",
    )
    op.drop_table("candidate_consensus", schema="ai")
