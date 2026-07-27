"""AI Candidate Lifecycle (STEP 11-13).

Revision ID: ae5f6a7b8c9d
Revises: ad4e5f6a7b8c

Safety: lifecycle rows only for promotion-created candidates (candidate_promotion_link).
No AI calls. Expire/revoke = status only. No hard delete.
"""

from __future__ import annotations

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ae5f6a7b8c9d"
down_revision: Union[str, Sequence[str], None] = "ad4e5f6a7b8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIFECYCLE_STATUS = (
    "'PROMOTED','ACTIVE_REVIEW','REVALIDATION_REQUIRED','STALE',"
    "'SUPERSEDED','EXPIRED','REVOKED','CANCELLED','ARCHIVED',"
    "'REVOCATION_REQUESTED','REVOCATION_BLOCKED','REVALIDATING','REVALIDATION_FAILED'"
)

_HEALTH_STATUS = (
    "'REVOKED','SUPERSEDED','EXPIRED','REVALIDATION_REQUIRED',"
    "'STALE','WARNING','HEALTHY','UNKNOWN'"
)

_REVALIDATION_STATUS = (
    "'REQUESTED','RUNNING','PASSED','PASSED_WITH_WARNING','FAILED','CANCELLED'"
)

_REVOCATION_STATUS = (
    "'REQUESTED','VALIDATING','BLOCKED','APPROVED','COMPLETED',"
    "'CANCELLED','FAILED'"
)

_SUPERSESSION_STATUS = "'ACTIVE','COMPLETED','CANCELLED'"

AI_LIFECYCLE_PERMISSIONS = (
    "AI_CANDIDATE_LIFECYCLE_VIEW",
    "AI_CANDIDATE_LIFECYCLE_VALIDATE",
    "AI_CANDIDATE_LIFECYCLE_REVALIDATE",
    "AI_CANDIDATE_LIFECYCLE_EXPIRE",
    "AI_CANDIDATE_LIFECYCLE_REVOKE_REQUEST",
    "AI_CANDIDATE_LIFECYCLE_REVOKE_APPROVE",
    "AI_CANDIDATE_LIFECYCLE_ARCHIVE",
    "AI_CANDIDATE_LIFECYCLE_SUPERSEDE",
    "AI_CANDIDATE_LIFECYCLE_AUDIT",
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")

    op.create_table(
        "candidate_lifecycle",
        sa.Column(
            "lifecycle_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "lifecycle_status",
            sa.String(40),
            nullable=False,
            server_default="PROMOTED",
        ),
        sa.Column(
            "health_status",
            sa.String(40),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column(
            "lifecycle_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("source_fingerprint", sa.String(64)),
        sa.Column(
            "source_changed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "revalidation_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("expiration_at", sa.DateTime(timezone=True)),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("last_validated_at", sa.DateTime(timezone=True)),
        sa.Column("last_revalidated_at", sa.DateTime(timezone=True)),
        sa.Column("status_reason_code", sa.String(80)),
        sa.Column("status_reason_message", sa.String(2000)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(100), nullable=False),
        sa.CheckConstraint(
            f"lifecycle_status IN ({_LIFECYCLE_STATUS})",
            name="ck_ai_cand_lifecycle_status",
        ),
        sa.CheckConstraint(
            f"health_status IN ({_HEALTH_STATUS})",
            name="ck_ai_cand_lifecycle_health",
        ),
        sa.UniqueConstraint("candidate_id", name="uq_ai_cand_lifecycle_candidate"),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["strategy.candidate_result.result_id"],
            name="fk_ai_cand_lifecycle_result",
            ondelete="RESTRICT",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_lifecycle_status",
        "candidate_lifecycle",
        ["lifecycle_status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_lifecycle_health",
        "candidate_lifecycle",
        ["health_status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_lifecycle_expiration",
        "candidate_lifecycle",
        ["expiration_at"],
        schema="ai",
    )

    op.create_table(
        "candidate_lifecycle_history",
        sa.Column(
            "history_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("previous_lifecycle_status", sa.String(40)),
        sa.Column("new_lifecycle_status", sa.String(40)),
        sa.Column("previous_health_status", sa.String(40)),
        sa.Column("new_health_status", sa.String(40)),
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
            ["candidate_id"],
            ["ai.candidate_lifecycle.candidate_id"],
            name="fk_ai_cand_lifecycle_hist_candidate",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_lifecycle_hist_candidate",
        "candidate_lifecycle_history",
        ["candidate_id"],
        schema="ai",
    )

    op.create_table(
        "candidate_provenance_snapshot",
        sa.Column(
            "snapshot_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("promotion_request_id", sa.BigInteger()),
        sa.Column("promotion_link_id", sa.BigInteger()),
        sa.Column("queue_id", sa.BigInteger()),
        sa.Column("source_type", sa.String(40)),
        sa.Column("source_id", sa.BigInteger()),
        sa.Column("source_result_hash", sa.String(64)),
        sa.Column("evidence_bundle_hash", sa.String(64)),
        sa.Column("queue_version_snapshot", sa.Integer()),
        sa.Column("candidate_result_hash", sa.String(64)),
        sa.Column("combined_source_fingerprint", sa.String(64)),
        sa.Column(
            "schema_version",
            sa.String(40),
            nullable=False,
            server_default="prov-1.0.0",
        ),
        sa.Column(
            "source_graph",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "candidate_id",
            name="uq_ai_cand_prov_snapshot_candidate",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["ai.candidate_lifecycle.candidate_id"],
            name="fk_ai_cand_prov_snapshot_candidate",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["promotion_request_id"],
            ["ai.candidate_promotion_request.promotion_request_id"],
            name="fk_ai_cand_prov_snapshot_prom_req",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["promotion_link_id"],
            ["ai.candidate_promotion_link.link_id"],
            name="fk_ai_cand_prov_snapshot_prom_link",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["queue_id"],
            ["ai.candidate_recommendation_queue.queue_id"],
            name="fk_ai_cand_prov_snapshot_queue",
            ondelete="SET NULL",
        ),
        schema="ai",
    )

    op.create_table(
        "candidate_revalidation",
        sa.Column(
            "revalidation_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("revalidation_key", sa.String(220), nullable=False),
        sa.Column(
            "revalidation_status",
            sa.String(40),
            nullable=False,
            server_default="REQUESTED",
        ),
        sa.Column("expected_fingerprint", sa.String(64)),
        sa.Column("actual_fingerprint", sa.String(64)),
        sa.Column(
            "fingerprint_match",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("warnings", postgresql.JSONB()),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("completed_by", sa.String(100)),
        sa.Column("reason", sa.String(500)),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"revalidation_status IN ({_REVALIDATION_STATUS})",
            name="ck_ai_cand_revalidation_status",
        ),
        sa.UniqueConstraint(
            "candidate_id",
            "revalidation_key",
            name="uq_ai_cand_revalidation_key",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["ai.candidate_lifecycle.candidate_id"],
            name="fk_ai_cand_revalidation_candidate",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_revalidation_candidate",
        "candidate_revalidation",
        ["candidate_id"],
        schema="ai",
    )

    op.create_table(
        "candidate_revocation",
        sa.Column(
            "revocation_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("revocation_key", sa.String(220), nullable=False),
        sa.Column(
            "revocation_status",
            sa.String(40),
            nullable=False,
            server_default="REQUESTED",
        ),
        sa.Column(
            "blocked_reasons",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("approved_by", sa.String(100)),
        sa.Column("reason", sa.String(500)),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"revocation_status IN ({_REVOCATION_STATUS})",
            name="ck_ai_cand_revocation_status",
        ),
        sa.UniqueConstraint(
            "candidate_id",
            "revocation_key",
            name="uq_ai_cand_revocation_key",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["ai.candidate_lifecycle.candidate_id"],
            name="fk_ai_cand_revocation_candidate",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_revocation_candidate",
        "candidate_revocation",
        ["candidate_id"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_cand_revocation_status",
        "candidate_revocation",
        ["revocation_status"],
        schema="ai",
    )

    op.create_table(
        "candidate_supersession",
        sa.Column(
            "supersession_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("previous_candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("replacement_candidate_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "supersession_status",
            sa.String(20),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("reason", sa.String(500)),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "previous_candidate_id <> replacement_candidate_id",
            name="ck_ai_cand_supersession_distinct",
        ),
        sa.CheckConstraint(
            f"supersession_status IN ({_SUPERSESSION_STATUS})",
            name="ck_ai_cand_supersession_status",
        ),
        sa.ForeignKeyConstraint(
            ["previous_candidate_id"],
            ["ai.candidate_lifecycle.candidate_id"],
            name="fk_ai_cand_supersession_previous",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_candidate_id"],
            ["ai.candidate_lifecycle.candidate_id"],
            name="fk_ai_cand_supersession_replacement",
            ondelete="RESTRICT",
        ),
        schema="ai",
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_ai_cand_supersession_active_previous
        ON ai.candidate_supersession (previous_candidate_id)
        WHERE supersession_status = 'ACTIVE'
        """
    )

    _backfill_lifecycle(op.get_bind())
    _seed_permissions(op.get_bind())


def _backfill_lifecycle(conn: Any) -> None:
    """COMPLETED promotion link → lifecycle + provenance snapshot."""
    conn.execute(
        sa.text(
            """
            INSERT INTO ai.candidate_lifecycle (
                candidate_id,
                lifecycle_status,
                health_status,
                source_fingerprint,
                expiration_at,
                last_validated_at,
                created_by,
                updated_by
            )
            SELECT
                l.candidate_result_id,
                'PROMOTED',
                CASE
                    WHEN r.source_result_hash IS NOT NULL
                         AND l.candidate_result_hash IS NOT NULL
                    THEN 'HEALTHY'
                    ELSE 'UNKNOWN'
                END,
                COALESCE(r.source_result_hash, l.candidate_result_hash),
                CASE
                    WHEN r.market_type = 'CRYPTO'
                    THEN COALESCE(r.committed_at, l.promoted_at) + INTERVAL '48 hours'
                    ELSE COALESCE(r.committed_at, l.promoted_at) + INTERVAL '7 days'
                END,
                COALESCE(r.committed_at, l.promoted_at),
                l.promoted_by,
                l.promoted_by
            FROM ai.candidate_promotion_link l
            JOIN ai.candidate_promotion_request r
              ON r.promotion_request_id = l.promotion_request_id
            WHERE r.promotion_status = 'COMPLETED'
              AND l.candidate_result_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM ai.candidate_lifecycle cl
                  WHERE cl.candidate_id = l.candidate_result_id
              )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO ai.candidate_provenance_snapshot (
                candidate_id,
                promotion_request_id,
                promotion_link_id,
                queue_id,
                source_type,
                source_id,
                source_result_hash,
                evidence_bundle_hash,
                queue_version_snapshot,
                candidate_result_hash,
                combined_source_fingerprint,
                source_graph
            )
            SELECT
                l.candidate_result_id,
                l.promotion_request_id,
                l.link_id,
                l.queue_id,
                r.source_type,
                r.source_id,
                r.source_result_hash,
                r.evidence_bundle_hash,
                r.queue_version_snapshot,
                l.candidate_result_hash,
                COALESCE(
                    r.source_result_hash,
                    l.candidate_result_hash
                ),
                jsonb_build_object(
                    'promotion_request_id', l.promotion_request_id,
                    'promotion_link_id', l.link_id,
                    'queue_id', l.queue_id,
                    'source_type', r.source_type,
                    'source_id', r.source_id,
                    'source_result_hash', r.source_result_hash,
                    'evidence_bundle_hash', r.evidence_bundle_hash,
                    'candidate_result_hash', l.candidate_result_hash
                )
            FROM ai.candidate_promotion_link l
            JOIN ai.candidate_promotion_request r
              ON r.promotion_request_id = l.promotion_request_id
            WHERE r.promotion_status = 'COMPLETED'
              AND l.candidate_result_id IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM ai.candidate_lifecycle cl
                  WHERE cl.candidate_id = l.candidate_result_id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM ai.candidate_provenance_snapshot ps
                  WHERE ps.candidate_id = l.candidate_result_id
              )
            """
        )
    )


def _seed_permissions(conn: Any) -> None:
    for code in AI_LIFECYCLE_PERMISSIONS:
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

    perm_list = ", ".join(f"'{p}'" for p in AI_LIFECYCLE_PERMISSIONS)
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
    perm_list = ", ".join(f"'{p}'" for p in AI_LIFECYCLE_PERMISSIONS)
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

    op.execute("DROP INDEX IF EXISTS ai.uq_ai_cand_supersession_active_previous")
    op.drop_table("candidate_supersession", schema="ai")
    op.drop_index(
        "ix_ai_cand_revocation_status",
        table_name="candidate_revocation",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_revocation_candidate",
        table_name="candidate_revocation",
        schema="ai",
    )
    op.drop_table("candidate_revocation", schema="ai")
    op.drop_index(
        "ix_ai_cand_revalidation_candidate",
        table_name="candidate_revalidation",
        schema="ai",
    )
    op.drop_table("candidate_revalidation", schema="ai")
    op.drop_table("candidate_provenance_snapshot", schema="ai")
    op.drop_index(
        "ix_ai_cand_lifecycle_hist_candidate",
        table_name="candidate_lifecycle_history",
        schema="ai",
    )
    op.drop_table("candidate_lifecycle_history", schema="ai")
    op.drop_index(
        "ix_ai_cand_lifecycle_expiration",
        table_name="candidate_lifecycle",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_lifecycle_health",
        table_name="candidate_lifecycle",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_cand_lifecycle_status",
        table_name="candidate_lifecycle",
        schema="ai",
    )
    op.drop_table("candidate_lifecycle", schema="ai")
