"""AI Candidate Recommendation Queue (STEP 11-11).

Revision ID: ac3d4e5f6a7b
Revises: ab2c3d4e5f6a

Safety: recommendation queue only — no strategy.candidate INSERT,
no trading/order/runtime side effects, APPROVED_FOR_CONSIDERATION ≠ candidate registration.
"""

from __future__ import annotations

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ac3d4e5f6a7b"
down_revision: Union[str, Sequence[str], None] = "ab2c3d4e5f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_QUEUE_STATUS = (
    "'DRAFT','QUEUED','ASSIGNED','UNDER_REVIEW','MORE_INFORMATION_REQUIRED',"
    "'APPROVED_FOR_CONSIDERATION','APPROVED_WITH_WARNINGS','REJECTED','ON_HOLD',"
    "'EXPIRED','WITHDRAWN','SUPERSEDED','NOT_ELIGIBLE','ARCHIVED'"
)

_PRIORITY = "'LOW','NORMAL','HIGH','URGENT'"

_SOURCE_TYPES = "'CANDIDATE_ASSESSMENT','CANDIDATE_CONSENSUS'"

_REVIEW_STATUS = "'DRAFT','SUBMITTED','AMENDED','WITHDRAWN'"

_DECISION = (
    "'PENDING','APPROVED_FOR_CONSIDERATION','APPROVED_WITH_WARNINGS','REJECTED','ON_HOLD',"
    "'MORE_INFORMATION_REQUIRED','NOT_ELIGIBLE','EXPIRED','WITHDRAWN'"
)

_ASSIGNMENT_STATUS = "'ACTIVE','ACCEPTED','COMPLETED','CANCELLED'"

_RESOLUTION_STATUS = "'OPEN','RESOLVED','DISMISSED'"

_SCORE_0_100 = "({col} IS NULL OR ({col} >= 0 AND {col} <= 100))"
_SCORE_0_5 = "({col} IS NULL OR ({col} >= 0 AND {col} <= 5))"

AI_QUEUE_PERMISSIONS = (
    "AI_CANDIDATE_QUEUE_VIEW",
    "AI_CANDIDATE_QUEUE_CREATE",
    "AI_CANDIDATE_QUEUE_ASSIGN",
    "AI_CANDIDATE_QUEUE_REVIEW",
    "AI_CANDIDATE_QUEUE_DECIDE",
    "AI_CANDIDATE_QUEUE_OVERRIDE",
    "AI_CANDIDATE_QUEUE_AUDIT",
    "AI_CANDIDATE_QUEUE_BATCH",
    "AI_CANDIDATE_QUEUE_EXPIRE",
    "AI_CANDIDATE_QUEUE_REQUEUE",
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")

    op.create_table(
        "candidate_recommendation_queue",
        sa.Column(
            "queue_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("queue_key", sa.String(220), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("candidate_assessment_id", sa.BigInteger()),
        sa.Column("candidate_consensus_id", sa.BigInteger()),
        sa.Column("market_type", sa.String(40), nullable=False),
        sa.Column("exchange_code", sa.String(20), nullable=False),
        sa.Column("instrument_id", sa.BigInteger()),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column(
            "queue_status",
            sa.String(40),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "priority",
            sa.String(20),
            nullable=False,
            server_default="NORMAL",
        ),
        sa.Column("source_result_hash", sa.String(64), nullable=False),
        sa.Column("evidence_bundle_hash", sa.String(64)),
        sa.Column("source_review_decision", sa.String(40)),
        sa.Column("source_quality_score", sa.Float()),
        sa.Column("analytical_score", sa.Float()),
        sa.Column("risk_score", sa.Float()),
        sa.Column("confidence", sa.Float()),
        sa.Column("agreement_level", sa.String(40)),
        sa.Column("disagreement_level", sa.String(40)),
        sa.Column("provider_diversity", sa.String(40)),
        sa.Column("eligibility_version", sa.String(40)),
        sa.Column("eligibility_snapshot", postgresql.JSONB()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_to", sa.String(100)),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("review_started_at", sa.DateTime(timezone=True)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_by_id", sa.BigInteger()),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("reason", sa.String(500)),
        sa.Column("correlation_id", sa.String(64)),
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
            f"source_type IN ({_SOURCE_TYPES})",
            name="ck_ai_cand_rec_queue_source_type",
        ),
        sa.CheckConstraint(
            f"queue_status IN ({_QUEUE_STATUS})",
            name="ck_ai_cand_rec_queue_status",
        ),
        sa.CheckConstraint(
            f"priority IN ({_PRIORITY})",
            name="ck_ai_cand_rec_queue_priority",
        ),
        sa.CheckConstraint(
            "("
            "(candidate_assessment_id IS NOT NULL "
            "AND candidate_consensus_id IS NULL "
            "AND source_type = 'CANDIDATE_ASSESSMENT') "
            "OR "
            "(candidate_consensus_id IS NOT NULL "
            "AND candidate_assessment_id IS NULL "
            "AND source_type = 'CANDIDATE_CONSENSUS')"
            ")",
            name="ck_ai_cand_rec_queue_source_xor",
        ),
        sa.CheckConstraint(
            _SCORE_0_100.format(col="analytical_score"),
            name="ck_ai_cand_rec_queue_analytical_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_100.format(col="risk_score"),
            name="ck_ai_cand_rec_queue_risk_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_100.format(col="source_quality_score"),
            name="ck_ai_cand_rec_queue_source_quality_score",
        ),
        sa.CheckConstraint(
            "(confidence IS NULL OR (confidence >= 0 AND confidence <= 1))",
            name="ck_ai_cand_rec_queue_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_assessment_id"],
            ["ai.candidate_assessment.assessment_id"],
            name="fk_ai_cand_rec_queue_assessment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_consensus_id"],
            ["ai.candidate_consensus.consensus_id"],
            name="fk_ai_cand_rec_queue_consensus",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("queue_key", name="uq_ai_cand_rec_queue_key"),
        sa.UniqueConstraint(
            "created_by",
            "idempotency_key",
            name="uq_ai_cand_rec_queue_idempotency",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_rec_queue_status",
        "candidate_recommendation_queue",
        ["queue_status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_rec_queue_symbol",
        "candidate_recommendation_queue",
        ["symbol"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_rec_queue_market_type",
        "candidate_recommendation_queue",
        ["market_type"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_rec_queue_assigned_to",
        "candidate_recommendation_queue",
        ["assigned_to"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_rec_queue_expires_at",
        "candidate_recommendation_queue",
        ["expires_at"],
        schema="ai",
    )

    op.create_table(
        "candidate_recommendation_review",
        sa.Column(
            "review_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("queue_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "review_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "review_status",
            sa.String(40),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("reviewer_id", sa.String(100), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("eligibility_score", sa.Float()),
        sa.Column("analytical_quality_score", sa.Float()),
        sa.Column("evidence_quality_score", sa.Float()),
        sa.Column("risk_awareness_score", sa.Float()),
        sa.Column("consistency_score", sa.Float()),
        sa.Column("safety_score", sa.Float()),
        sa.Column("overall_score", sa.Float()),
        sa.Column(
            "recommendation_scope",
            sa.String(40),
            nullable=False,
            server_default="CONSIDERATION_ONLY",
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("amended_from_id", sa.BigInteger()),
        sa.Column("amendment_reason", sa.String(500)),
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
            f"review_status IN ({_REVIEW_STATUS})",
            name="ck_ai_cand_rec_review_status",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="eligibility_score"),
            name="ck_ai_cand_rec_review_eligibility_score",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="analytical_quality_score"),
            name="ck_ai_cand_rec_review_analytical_quality",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="evidence_quality_score"),
            name="ck_ai_cand_rec_review_evidence_quality",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="risk_awareness_score"),
            name="ck_ai_cand_rec_review_risk_awareness",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="consistency_score"),
            name="ck_ai_cand_rec_review_consistency",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="safety_score"),
            name="ck_ai_cand_rec_review_safety",
        ),
        sa.CheckConstraint(
            _SCORE_0_5.format(col="overall_score"),
            name="ck_ai_cand_rec_review_overall",
        ),
        sa.ForeignKeyConstraint(
            ["queue_id"],
            ["ai.candidate_recommendation_queue.queue_id"],
            name="fk_ai_cand_rec_review_queue",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "queue_id",
            "review_version",
            name="uq_ai_cand_rec_review_version",
        ),
        schema="ai",
    )

    op.create_table(
        "candidate_recommendation_finding",
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
        sa.Column("description_sanitized", sa.String(2000)),
        sa.Column(
            "requires_resolution",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "resolution_status",
            sa.String(40),
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"resolution_status IN ({_RESOLUTION_STATUS})",
            name="ck_ai_cand_rec_finding_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["ai.candidate_recommendation_review.review_id"],
            name="fk_ai_cand_rec_finding_review",
            ondelete="CASCADE",
        ),
        schema="ai",
    )

    op.create_table(
        "candidate_recommendation_decision",
        sa.Column(
            "decision_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("queue_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "decision_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("decision_reason", sa.String(500)),
        sa.Column("warning_conditions", postgresql.JSONB()),
        sa.Column("decided_by", sa.String(100), nullable=False),
        sa.Column(
            "manager_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("override_reason", sa.String(500)),
        sa.Column("source_result_hash_at_decision", sa.String(64)),
        sa.Column("evidence_bundle_hash_at_decision", sa.String(64)),
        sa.Column("source_review_decision_at_decision", sa.String(40)),
        sa.Column("analytical_score_at_decision", sa.Float()),
        sa.Column("risk_score_at_decision", sa.Float()),
        sa.Column("confidence_at_decision", sa.Float()),
        sa.Column("agreement_level_at_decision", sa.String(40)),
        sa.Column("disagreement_level_at_decision", sa.String(40)),
        sa.Column(
            "critical_findings_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "unresolved_high_findings_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("eligibility_version", sa.String(40)),
        sa.Column("review_formula_version", sa.String(40)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"decision IN ({_DECISION})",
            name="ck_ai_cand_rec_decision",
        ),
        sa.ForeignKeyConstraint(
            ["queue_id"],
            ["ai.candidate_recommendation_queue.queue_id"],
            name="fk_ai_cand_rec_decision_queue",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "queue_id",
            "decision_version",
            name="uq_ai_cand_rec_decision_version",
        ),
        schema="ai",
    )

    op.create_table(
        "candidate_recommendation_history",
        sa.Column(
            "history_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("queue_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("previous_status", sa.String(40)),
        sa.Column("new_status", sa.String(40)),
        sa.Column("reason", sa.String(500)),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["queue_id"],
            ["ai.candidate_recommendation_queue.queue_id"],
            name="fk_ai_cand_rec_history_queue",
            ondelete="CASCADE",
        ),
        schema="ai",
    )

    op.create_table(
        "candidate_recommendation_assignment",
        sa.Column(
            "assignment_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("queue_id", sa.BigInteger(), nullable=False),
        sa.Column("assignee_id", sa.String(100), nullable=False),
        sa.Column("assignment_status", sa.String(40), nullable=False),
        sa.Column("assigned_by", sa.String(100), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"assignment_status IN ({_ASSIGNMENT_STATUS})",
            name="ck_ai_cand_rec_assignment_status",
        ),
        sa.ForeignKeyConstraint(
            ["queue_id"],
            ["ai.candidate_recommendation_queue.queue_id"],
            name="fk_ai_cand_rec_assignment_queue",
            ondelete="CASCADE",
        ),
        schema="ai",
    )

    _seed_permissions(op.get_bind())


def _seed_permissions(conn: Any) -> None:
    for code in AI_QUEUE_PERMISSIONS:
        conn.execute(
            sa.text(
                """
                INSERT INTO auth.permission
                    (code, name, category, description)
                VALUES (:code, :name, 'ai', :name)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code, "name": code.replace("_", " ").title()},
        )

    perm_list = ", ".join(f"'{p}'" for p in AI_QUEUE_PERMISSIONS)
    conn.execute(
        sa.text(
            f"""
            INSERT INTO auth.role_permission (role_id, permission_id)
            SELECT r.role_id, p.permission_id
            FROM auth.role r
            CROSS JOIN auth.permission p
            WHERE r.code = 'admin'
              AND p.code IN ({perm_list})
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    perm_list = ", ".join(f"'{p}'" for p in AI_QUEUE_PERMISSIONS)
    conn.execute(
        sa.text(
            f"""
            DELETE FROM auth.role_permission
            WHERE permission_id IN (
                SELECT permission_id FROM auth.permission
                WHERE code IN ({perm_list})
            )
            """
        )
    )
    conn.execute(
        sa.text(
            f"""
            DELETE FROM auth.permission
            WHERE code IN ({perm_list})
            """
        )
    )

    op.drop_table("candidate_recommendation_assignment", schema="ai")
    op.drop_table("candidate_recommendation_history", schema="ai")
    op.drop_table("candidate_recommendation_decision", schema="ai")
    op.drop_table("candidate_recommendation_finding", schema="ai")
    op.drop_table("candidate_recommendation_review", schema="ai")
    op.drop_index(
        "ix_ai_cand_rec_queue_expires_at",
        table_name="candidate_recommendation_queue",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_rec_queue_assigned_to",
        table_name="candidate_recommendation_queue",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_rec_queue_market_type",
        table_name="candidate_recommendation_queue",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_rec_queue_symbol",
        table_name="candidate_recommendation_queue",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_rec_queue_status",
        table_name="candidate_recommendation_queue",
        schema="ai",
    )
    op.drop_table("candidate_recommendation_queue", schema="ai")
