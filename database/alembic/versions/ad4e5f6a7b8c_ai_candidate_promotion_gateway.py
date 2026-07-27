"""AI Candidate Promotion Gateway (STEP 11-12).

Revision ID: ad4e5f6a7b8c
Revises: ac3d4e5f6a7b

Safety: only Commit inserts strategy.candidate_run/result (AI_REVIEW_PROMOTION).
Create/Validate/Dry-run/Approve → Candidate INSERT 0.
"""

from __future__ import annotations

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ad4e5f6a7b8c"
down_revision: Union[str, Sequence[str], None] = "ac3d4e5f6a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROMOTION_STATUS = (
    "'DRAFT','VALIDATING','VALIDATED','VALIDATED_WITH_WARNINGS',"
    "'DRY_RUN_READY','DRY_RUN_COMPLETED','FIRST_APPROVAL_PENDING','FIRST_APPROVED',"
    "'FINAL_APPROVAL_PENDING','FINAL_APPROVED','COMMIT_PENDING','COMMITTING',"
    "'COMPLETED','BLOCKED','REJECTED','CANCELLED','EXPIRED','STALE','FAILED',"
    "'ROLLBACK_REQUIRED','ROLLED_BACK','ARCHIVED'"
)

_SOURCE_TYPES = "'CANDIDATE_ASSESSMENT','CANDIDATE_CONSENSUS'"

_VALIDATION_TYPES = (
    "'ELIGIBILITY','SOURCE','QUEUE','EXPIRATION','FINDING','INSTRUMENT',"
    "'EXISTING_CANDIDATE','MAPPING','SIDE_EFFECT','COMMIT_PRECONDITION'"
)

_VALIDATION_STATUS = "'PASS','FAIL','WARN','SKIP'"

_SEVERITIES = "'INFO','LOW','MEDIUM','HIGH','CRITICAL'"

_APPROVAL_STAGES = "'FIRST','FINAL','COMMIT_CONFIRM'"

_APPROVAL_STATUS = "'PENDING','APPROVED','REJECTED','REVOKED','EXPIRED'"

_ROLLBACK_STATUS = "'NONE','ROLLED_BACK','BLOCKED'"

AI_PROMOTION_PERMISSIONS = (
    "AI_CANDIDATE_PROMOTION_VIEW",
    "AI_CANDIDATE_PROMOTION_CREATE",
    "AI_CANDIDATE_PROMOTION_VALIDATE",
    "AI_CANDIDATE_PROMOTION_DRY_RUN",
    "AI_CANDIDATE_PROMOTION_FIRST_APPROVE",
    "AI_CANDIDATE_PROMOTION_FINAL_APPROVE",
    "AI_CANDIDATE_PROMOTION_COMMIT",
    "AI_CANDIDATE_PROMOTION_CANCEL",
    "AI_CANDIDATE_PROMOTION_ROLLBACK",
    "AI_CANDIDATE_PROMOTION_OVERRIDE",
    "AI_CANDIDATE_PROMOTION_AUDIT",
    "AI_CANDIDATE_PROMOTION_BATCH",
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")

    # DAILY Run만 exchange+date 유일 — AI_REVIEW_PROMOTION은 동일일 다건 허용
    op.drop_constraint(
        "uq_candidate_run_exchange_date_type",
        "candidate_run",
        schema="strategy",
        type_="unique",
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_candidate_run_daily_exchange_date
        ON strategy.candidate_run (exchange_code, as_of_date)
        WHERE run_type = 'DAILY'
        """
    )

    op.create_table(
        "candidate_promotion_request",
        sa.Column(
            "promotion_request_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("promotion_key", sa.String(220), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("queue_id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("market_type", sa.String(40), nullable=False),
        sa.Column("exchange_code", sa.String(20), nullable=False),
        sa.Column("instrument_id", sa.BigInteger()),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column(
            "promotion_status",
            sa.String(40),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("queue_decision_snapshot", sa.String(40)),
        sa.Column("queue_version_snapshot", sa.Integer()),
        sa.Column("source_result_hash", sa.String(64), nullable=False),
        sa.Column("evidence_bundle_hash", sa.String(64)),
        sa.Column("eligibility_version", sa.String(40)),
        sa.Column("mapping_version", sa.String(40), nullable=False),
        sa.Column("score_formula_version", sa.String(40), nullable=False),
        sa.Column("warning_conditions", postgresql.JSONB()),
        sa.Column("requested_reason", sa.String(500), nullable=False),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column("dry_run_at", sa.DateTime(timezone=True)),
        sa.Column("first_approved_at", sa.DateTime(timezone=True)),
        sa.Column("final_approved_at", sa.DateTime(timezone=True)),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_run_id", sa.BigInteger()),
        sa.Column("candidate_result_id", sa.BigInteger()),
        sa.Column("commit_idempotency_key", sa.String(64)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message_sanitized", sa.String(2000)),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
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
            f"promotion_status IN ({_PROMOTION_STATUS})",
            name="ck_ai_cand_prom_req_status",
        ),
        sa.CheckConstraint(
            f"source_type IN ({_SOURCE_TYPES})",
            name="ck_ai_cand_prom_req_source_type",
        ),
        sa.UniqueConstraint("promotion_key", name="uq_ai_cand_prom_req_key"),
        sa.UniqueConstraint(
            "requested_by",
            "idempotency_key",
            name="uq_ai_cand_prom_req_idempotency",
        ),
        sa.ForeignKeyConstraint(
            ["queue_id"],
            ["ai.candidate_recommendation_queue.queue_id"],
            name="fk_ai_cand_prom_req_queue",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_run_id"],
            ["strategy.candidate_run.run_id"],
            name="fk_ai_cand_prom_req_run",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_result_id"],
            ["strategy.candidate_result.result_id"],
            name="fk_ai_cand_prom_req_result",
            ondelete="SET NULL",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_prom_req_queue_id",
        "candidate_promotion_request",
        ["queue_id"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_prom_req_status",
        "candidate_promotion_request",
        ["promotion_status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_prom_req_symbol",
        "candidate_promotion_request",
        ["exchange_code", "symbol"],
        schema="ai",
    )

    op.create_table(
        "candidate_promotion_validation",
        sa.Column(
            "validation_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("promotion_request_id", sa.BigInteger(), nullable=False),
        sa.Column("validation_version", sa.Integer(), nullable=False),
        sa.Column("validation_type", sa.String(40), nullable=False),
        sa.Column("validation_status", sa.String(20), nullable=False),
        sa.Column("check_code", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("expected_value_hash", sa.String(64)),
        sa.Column("actual_value_hash", sa.String(64)),
        sa.Column("message_sanitized", sa.String(2000)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"validation_type IN ({_VALIDATION_TYPES})",
            name="ck_ai_cand_prom_val_type",
        ),
        sa.CheckConstraint(
            f"validation_status IN ({_VALIDATION_STATUS})",
            name="ck_ai_cand_prom_val_status",
        ),
        sa.CheckConstraint(
            f"severity IN ({_SEVERITIES})",
            name="ck_ai_cand_prom_val_severity",
        ),
        sa.ForeignKeyConstraint(
            ["promotion_request_id"],
            ["ai.candidate_promotion_request.promotion_request_id"],
            name="fk_ai_cand_prom_val_request",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_prom_val_request",
        "candidate_promotion_validation",
        ["promotion_request_id", "validation_version"],
        schema="ai",
    )

    op.create_table(
        "candidate_promotion_dry_run",
        sa.Column(
            "dry_run_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("promotion_request_id", sa.BigInteger(), nullable=False),
        sa.Column("dry_run_version", sa.Integer(), nullable=False),
        sa.Column(
            "candidate_run_preview_jsonb",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "candidate_result_preview_jsonb",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "conflict_summary_jsonb",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "validation_summary_jsonb",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "side_effect_summary_jsonb",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "promotion_request_id",
            "dry_run_version",
            name="uq_ai_cand_prom_dry_run_version",
        ),
        sa.ForeignKeyConstraint(
            ["promotion_request_id"],
            ["ai.candidate_promotion_request.promotion_request_id"],
            name="fk_ai_cand_prom_dry_run_request",
            ondelete="CASCADE",
        ),
        schema="ai",
    )

    op.create_table(
        "candidate_promotion_approval",
        sa.Column(
            "approval_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("promotion_request_id", sa.BigInteger(), nullable=False),
        sa.Column("approval_stage", sa.String(20), nullable=False),
        sa.Column("approval_status", sa.String(20), nullable=False),
        sa.Column("approved_by", sa.String(100), nullable=False),
        sa.Column("approval_reason", sa.String(500)),
        sa.Column("warning_acknowledgements", postgresql.JSONB()),
        sa.Column("source_result_hash_at_approval", sa.String(64)),
        sa.Column("evidence_bundle_hash_at_approval", sa.String(64)),
        sa.Column("queue_version_at_approval", sa.Integer()),
        sa.Column("dry_run_result_hash", sa.String(64)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "version",
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
        sa.CheckConstraint(
            f"approval_stage IN ({_APPROVAL_STAGES})",
            name="ck_ai_cand_prom_appr_stage",
        ),
        sa.CheckConstraint(
            f"approval_status IN ({_APPROVAL_STATUS})",
            name="ck_ai_cand_prom_appr_status",
        ),
        sa.ForeignKeyConstraint(
            ["promotion_request_id"],
            ["ai.candidate_promotion_request.promotion_request_id"],
            name="fk_ai_cand_prom_appr_request",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_prom_appr_request",
        "candidate_promotion_approval",
        ["promotion_request_id", "approval_stage"],
        schema="ai",
    )

    op.create_table(
        "candidate_promotion_link",
        sa.Column(
            "link_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("promotion_request_id", sa.BigInteger(), nullable=False),
        sa.Column("queue_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_run_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_result_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_result_hash", sa.String(64), nullable=False),
        sa.Column("promoted_by", sa.String(100), nullable=False),
        sa.Column(
            "promoted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "rollback_status",
            sa.String(20),
            nullable=False,
            server_default="NONE",
        ),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True)),
        sa.Column("rollback_reason", sa.String(500)),
        sa.CheckConstraint(
            f"rollback_status IN ({_ROLLBACK_STATUS})",
            name="ck_ai_cand_prom_link_rollback",
        ),
        sa.ForeignKeyConstraint(
            ["promotion_request_id"],
            ["ai.candidate_promotion_request.promotion_request_id"],
            name="fk_ai_cand_prom_link_request",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["queue_id"],
            ["ai.candidate_recommendation_queue.queue_id"],
            name="fk_ai_cand_prom_link_queue",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_run_id"],
            ["strategy.candidate_run.run_id"],
            name="fk_ai_cand_prom_link_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_result_id"],
            ["strategy.candidate_result.result_id"],
            name="fk_ai_cand_prom_link_result",
            ondelete="RESTRICT",
        ),
        schema="ai",
    )

    op.create_table(
        "candidate_promotion_history",
        sa.Column(
            "history_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("promotion_request_id", sa.BigInteger(), nullable=False),
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
            ["promotion_request_id"],
            ["ai.candidate_promotion_request.promotion_request_id"],
            name="fk_ai_cand_prom_hist_request",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_prom_hist_request",
        "candidate_promotion_history",
        ["promotion_request_id"],
        schema="ai",
    )

    _seed_permissions(op.get_bind())


def _seed_permissions(conn: Any) -> None:
    for code in AI_PROMOTION_PERMISSIONS:
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

    perm_list = ", ".join(f"'{p}'" for p in AI_PROMOTION_PERMISSIONS)
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
    perm_list = ", ".join(f"'{p}'" for p in AI_PROMOTION_PERMISSIONS)
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

    op.drop_index(
        "ix_ai_cand_prom_hist_request",
        table_name="candidate_promotion_history",
        schema="ai",
    )
    op.drop_table("candidate_promotion_history", schema="ai")
    op.drop_table("candidate_promotion_link", schema="ai")
    op.drop_index(
        "ix_ai_cand_prom_appr_request",
        table_name="candidate_promotion_approval",
        schema="ai",
    )
    op.drop_table("candidate_promotion_approval", schema="ai")
    op.drop_table("candidate_promotion_dry_run", schema="ai")
    op.drop_index(
        "ix_ai_cand_prom_val_request",
        table_name="candidate_promotion_validation",
        schema="ai",
    )
    op.drop_table("candidate_promotion_validation", schema="ai")
    op.drop_index(
        "ix_ai_cand_prom_req_symbol",
        table_name="candidate_promotion_request",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_prom_req_status",
        table_name="candidate_promotion_request",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_prom_req_queue_id",
        table_name="candidate_promotion_request",
        schema="ai",
    )
    op.drop_table("candidate_promotion_request", schema="ai")

    op.execute("DROP INDEX IF EXISTS strategy.uq_candidate_run_daily_exchange_date")
    op.create_unique_constraint(
        "uq_candidate_run_exchange_date_type",
        "candidate_run",
        ["exchange_code", "as_of_date", "run_type"],
        schema="strategy",
    )
