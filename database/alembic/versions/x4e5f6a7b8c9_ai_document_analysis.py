"""AI News/Disclosure document analysis (STEP 11-6).

Revision ID: x4e5f6a7b8c9
Revises: w3d4e5f6a7b8
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "x4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "w3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _checksum(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text_checksum(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")

    op.create_table(
        "document_analysis",
        sa.Column(
            "document_analysis_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("analysis_key", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("document_type", sa.String(20), nullable=False),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("source_document_key", sa.String(120), nullable=False),
        sa.Column(
            "source_version",
            sa.String(40),
            nullable=False,
            server_default="1",
        ),
        sa.Column("market_type", sa.String(40)),
        sa.Column("symbol", sa.String(30)),
        sa.Column("company_id", sa.String(20)),
        sa.Column("execution_request_id", sa.BigInteger()),
        sa.Column("execution_result_id", sa.BigInteger()),
        sa.Column("task_type", sa.String(60), nullable=False),
        sa.Column(
            "analysis_status",
            sa.String(40),
            nullable=False,
            server_default="DRAFT_ANALYSIS",
        ),
        sa.Column(
            "execution_mode",
            sa.String(20),
            nullable=False,
            server_default="MOCK",
        ),
        sa.Column(
            "data_classification",
            sa.String(20),
            nullable=False,
            server_default="PUBLIC",
        ),
        sa.Column("prompt_template_id", sa.BigInteger()),
        sa.Column("prompt_version_id", sa.BigInteger()),
        sa.Column("output_schema_id", sa.BigInteger()),
        sa.Column("policy_ids", postgresql.JSONB()),
        sa.Column("provider_code", sa.String(40)),
        sa.Column("model", sa.String(200)),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("normalized_content_hash", sa.String(64)),
        sa.Column("result_hash", sa.String(64)),
        sa.Column("confidence", sa.Float()),
        sa.Column("importance_score", sa.Float()),
        sa.Column("relevance_score", sa.Float()),
        sa.Column("sentiment_score", sa.Float()),
        sa.Column("risk_level", sa.String(40)),
        sa.Column(
            "chunk_count", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("safe_result", postgresql.JSONB()),
        sa.Column("warnings", postgresql.JSONB()),
        sa.Column("unresolved_entities", postgresql.JSONB()),
        sa.Column("unmatched_symbols", postgresql.JSONB()),
        sa.Column(
            "source_missing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("analyzed_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_by_id", sa.BigInteger()),
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
            "document_type IN ('NEWS', 'DISCLOSURE')",
            name="ck_ai_doc_analysis_type",
        ),
        sa.CheckConstraint(
            "analysis_status IN ("
            "'DRAFT_ANALYSIS','QUEUED','RUNNING','VALIDATED_ANALYSIS',"
            "'VALIDATED_WITH_WARNINGS','BLOCKED','INVALID','FAILED',"
            "'CANCELLED','SUPERSEDED')",
            name="ck_ai_doc_analysis_status",
        ),
        sa.CheckConstraint(
            "data_classification IN "
            "('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')",
            name="ck_ai_doc_analysis_classification",
        ),
        sa.ForeignKeyConstraint(
            ["execution_request_id"],
            ["ai.execution_request.execution_request_id"],
            name="fk_ai_doc_analysis_exec_request",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("analysis_key", name="uq_ai_document_analysis_key"),
        sa.UniqueConstraint(
            "created_by",
            "idempotency_key",
            name="uq_ai_document_analysis_idempotency",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_doc_analysis_type_status",
        "document_analysis",
        ["document_type", "analysis_status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_doc_analysis_source",
        "document_analysis",
        ["document_type", "source_document_id"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_doc_analysis_source_key",
        "document_analysis",
        ["source_document_key"],
        schema="ai",
    )

    op.create_table(
        "document_analysis_topic",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("document_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_code", sa.String(80), nullable=False),
        sa.Column("topic_name", sa.String(200), nullable=False),
        sa.Column("score", sa.Float()),
        sa.Column("evidence_summary", sa.String(500)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_analysis_id"],
            ["ai.document_analysis.document_analysis_id"],
            name="fk_ai_doc_topic_analysis",
            ondelete="CASCADE",
        ),
        schema="ai",
    )

    op.create_table(
        "document_analysis_entity",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("document_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_code", sa.String(40)),
        sa.Column("entity_name", sa.String(200), nullable=False),
        sa.Column("relevance", sa.Float()),
        sa.Column("sentiment", sa.String(40)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_analysis_id"],
            ["ai.document_analysis.document_analysis_id"],
            name="fk_ai_doc_entity_analysis",
            ondelete="CASCADE",
        ),
        schema="ai",
    )

    op.create_table(
        "document_analysis_citation",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("document_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("citation_type", sa.String(40), nullable=False),
        sa.Column("source_ref", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300)),
        sa.Column("excerpt_hash", sa.String(64)),
        sa.Column("position_start", sa.Integer()),
        sa.Column("position_end", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_analysis_id"],
            ["ai.document_analysis.document_analysis_id"],
            name="fk_ai_doc_citation_analysis",
            ondelete="CASCADE",
        ),
        schema="ai",
    )

    op.create_table(
        "document_analysis_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("document_analysis_id", sa.BigInteger(), nullable=False),
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
            ["document_analysis_id"],
            ["ai.document_analysis.document_analysis_id"],
            name="fk_ai_doc_history_analysis",
            ondelete="CASCADE",
        ),
        schema="ai",
    )

    op.create_table(
        "document_analysis_news_link",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("document_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_analysis_id"],
            ["ai.document_analysis.document_analysis_id"],
            name="fk_ai_doc_news_link_analysis",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["news.news_article.article_id"],
            name="fk_ai_doc_news_link_article",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "document_analysis_id",
            name="uq_ai_doc_news_link_analysis",
        ),
        schema="ai",
    )

    op.create_table(
        "document_analysis_disclosure_link",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("document_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("disclosure_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_analysis_id"],
            ["ai.document_analysis.document_analysis_id"],
            name="fk_ai_doc_disclosure_link_analysis",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["disclosure_id"],
            ["disclosure.dart_disclosure.disclosure_id"],
            name="fk_ai_doc_disclosure_link_disclosure",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "document_analysis_id",
            name="uq_ai_doc_disclosure_link_analysis",
        ),
        schema="ai",
    )

    # NEWS schema 갱신 + DISCLOSURE schema/prompt seed (idempotent)
    conn = op.get_bind()
    _seed_disclosure_and_refresh_news(conn)


def _seed_disclosure_and_refresh_news(conn: Any) -> None:
    from stock_platform.ai.prompt.seed_data import (
        DISCLOSURE_ANALYSIS_RESULT_V1,
        NEWS_ANALYSIS_RESULT_V1,
        SEED_PROMPTS,
    )

    # NEWS schema json 갱신 (기존 row)
    news_js = NEWS_ANALYSIS_RESULT_V1
    conn.execute(
        sa.text(
            """
            UPDATE ai.output_schema
            SET json_schema = CAST(:js AS jsonb),
                checksum = :checksum,
                updated_by = 'SEED_11_6',
                updated_at = now()
            WHERE code = 'NEWS_ANALYSIS_RESULT_V1'
            """
        ),
        {
            "js": json.dumps(news_js, ensure_ascii=False),
            "checksum": _checksum(news_js),
        },
    )

    exists = conn.execute(
        sa.text(
            "SELECT output_schema_id FROM ai.output_schema "
            "WHERE code = 'DISCLOSURE_ANALYSIS_RESULT_V1'"
        )
    ).scalar()
    if exists is None:
        result = conn.execute(
            sa.text(
                """
                INSERT INTO ai.output_schema (
                    code, name, task_type, schema_version, json_schema,
                    strict_mode, additional_properties_allowed, status,
                    checksum, created_by, updated_by
                ) VALUES (
                    'DISCLOSURE_ANALYSIS_RESULT_V1',
                    'Disclosure Analysis Result v1',
                    'DISCLOSURE_ANALYSIS',
                    '1.0',
                    CAST(:js AS jsonb),
                    true, false, 'ACTIVE',
                    :checksum, 'SEED', 'SEED'
                )
                RETURNING output_schema_id
                """
            ),
            {
                "js": json.dumps(DISCLOSURE_ANALYSIS_RESULT_V1, ensure_ascii=False),
                "checksum": _checksum(DISCLOSURE_ANALYSIS_RESULT_V1),
            },
        )
        schema_id = int(result.scalar_one())
    else:
        schema_id = int(exists)
        conn.execute(
            sa.text(
                """
                UPDATE ai.output_schema
                SET json_schema = CAST(:js AS jsonb),
                    checksum = :checksum,
                    status = 'ACTIVE',
                    updated_by = 'SEED_11_6',
                    updated_at = now()
                WHERE output_schema_id = :id
                """
            ),
            {
                "js": json.dumps(DISCLOSURE_ANALYSIS_RESULT_V1, ensure_ascii=False),
                "checksum": _checksum(DISCLOSURE_ANALYSIS_RESULT_V1),
                "id": schema_id,
            },
        )

    prompt_seed = next(
        (p for p in SEED_PROMPTS if p["code"] == "DISCLOSURE_ANALYSIS_BASE"),
        None,
    )
    if prompt_seed is None:
        return

    policy_id = conn.execute(
        sa.text(
            "SELECT policy_definition_id FROM ai.policy_definition "
            "WHERE code = :code ORDER BY version DESC LIMIT 1"
        ),
        {"code": prompt_seed["policy_code"]},
    ).scalar()

    tpl_exists = conn.execute(
        sa.text(
            "SELECT prompt_template_id FROM ai.prompt_template "
            "WHERE code = 'DISCLOSURE_ANALYSIS_BASE'"
        )
    ).scalar()
    if tpl_exists is None:
        tpl = conn.execute(
            sa.text(
                """
                INSERT INTO ai.prompt_template (
                    code, name, task_type, description, status,
                    created_by, updated_by
                ) VALUES (
                    :code, :name, :task_type, :description, 'DRAFT',
                    'SEED', 'SEED'
                )
                RETURNING prompt_template_id
                """
            ),
            {
                "code": prompt_seed["code"],
                "name": prompt_seed["name"],
                "task_type": prompt_seed["task_type"],
                "description": "STEP 11-6 seed (DRAFT until operator activates)",
            },
        )
        template_id = int(tpl.scalar_one())
        checksum = _text_checksum(
            prompt_seed["system"],
            prompt_seed["user"],
            prompt_seed.get("context") or "",
        )
        ver = conn.execute(
            sa.text(
                """
                INSERT INTO ai.prompt_template_version (
                    prompt_template_id, version,
                    system_template, user_template, context_template,
                    variable_schema, required_capabilities,
                    output_schema_id, policy_id,
                    change_reason, checksum, status, created_by
                ) VALUES (
                    :tid, 1,
                    :system, :user, :context,
                    CAST(:var_schema AS jsonb),
                    CAST(:caps AS jsonb),
                    :schema_id, :policy_id,
                    'SEED', :checksum, 'DRAFT', 'SEED'
                )
                RETURNING prompt_template_version_id
                """
            ),
            {
                "tid": template_id,
                "system": prompt_seed["system"],
                "user": prompt_seed["user"],
                "context": prompt_seed.get("context") or "",
                "var_schema": json.dumps(
                    prompt_seed["variable_schema"], ensure_ascii=False
                ),
                "caps": json.dumps(prompt_seed["capabilities"]),
                "schema_id": schema_id,
                "policy_id": policy_id,
                "checksum": checksum,
            },
        )
        version_id = int(ver.scalar_one())
        conn.execute(
            sa.text(
                """
                UPDATE ai.prompt_template
                SET active_version_id = :vid
                WHERE prompt_template_id = :tid
                """
            ),
            {"vid": version_id, "tid": template_id},
        )

    # NEWS prompt user template delimiter 보강 (DRAFT 유지)
    news_seed = next(
        (p for p in SEED_PROMPTS if p["code"] == "NEWS_ANALYSIS_BASE"),
        None,
    )
    if news_seed:
        conn.execute(
            sa.text(
                """
                UPDATE ai.prompt_template_version v
                SET system_template = :system,
                    user_template = :user,
                    checksum = :checksum
                FROM ai.prompt_template t
                WHERE t.prompt_template_id = v.prompt_template_id
                  AND t.code = 'NEWS_ANALYSIS_BASE'
                  AND v.version = 1
                """
            ),
            {
                "system": news_seed["system"],
                "user": news_seed["user"],
                "checksum": _text_checksum(
                    news_seed["system"],
                    news_seed["user"],
                    news_seed.get("context") or "",
                ),
            },
        )


def downgrade() -> None:
    op.drop_table("document_analysis_disclosure_link", schema="ai")
    op.drop_table("document_analysis_news_link", schema="ai")
    op.drop_table("document_analysis_history", schema="ai")
    op.drop_table("document_analysis_citation", schema="ai")
    op.drop_table("document_analysis_entity", schema="ai")
    op.drop_table("document_analysis_topic", schema="ai")
    op.drop_table("document_analysis", schema="ai")

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM ai.prompt_template_version
            WHERE prompt_template_id IN (
                SELECT prompt_template_id FROM ai.prompt_template
                WHERE code = 'DISCLOSURE_ANALYSIS_BASE'
            )
            """
        )
    )
    conn.execute(
        sa.text(
            "DELETE FROM ai.prompt_template "
            "WHERE code = 'DISCLOSURE_ANALYSIS_BASE'"
        )
    )
    conn.execute(
        sa.text(
            "DELETE FROM ai.output_schema "
            "WHERE code = 'DISCLOSURE_ANALYSIS_RESULT_V1'"
        )
    )
