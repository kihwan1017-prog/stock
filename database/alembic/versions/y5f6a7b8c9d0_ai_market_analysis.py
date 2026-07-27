"""AI Chart/Market analysis (STEP 11-7).

Revision ID: y5f6a7b8c9d0
Revises: x4e5f6a7b8c9
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "y5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "x4e5f6a7b8c9"
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
        "market_analysis",
        sa.Column(
            "market_analysis_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("analysis_key", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("analysis_type", sa.String(40), nullable=False),
        sa.Column("market_type", sa.String(40), nullable=False),
        sa.Column("exchange_code", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(40)),
        sa.Column("timeframe", sa.String(20)),
        sa.Column("snapshot_key", sa.String(200), nullable=False),
        sa.Column(
            "snapshot_version",
            sa.String(40),
            nullable=False,
            server_default="1",
        ),
        sa.Column("snapshot_at", sa.DateTime(timezone=True)),
        sa.Column("data_from", sa.Date()),
        sa.Column("data_to", sa.Date()),
        sa.Column(
            "candle_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("indicator_version", sa.String(40)),
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
            sa.String(40),
            nullable=False,
            server_default="PUBLIC",
        ),
        sa.Column("prompt_template_id", sa.BigInteger()),
        sa.Column("prompt_version_id", sa.BigInteger()),
        sa.Column("output_schema_id", sa.BigInteger()),
        sa.Column("policy_ids", postgresql.JSONB()),
        sa.Column("provider_code", sa.String(40)),
        sa.Column("model", sa.String(200)),
        sa.Column("input_hash", sa.String(64)),
        sa.Column("snapshot_hash", sa.String(64)),
        sa.Column("result_hash", sa.String(64)),
        sa.Column("confidence", sa.Float()),
        sa.Column("trend_classification", sa.String(40)),
        sa.Column("volatility_level", sa.String(40)),
        sa.Column("market_regime", sa.String(40)),
        sa.Column(
            "data_quality_status",
            sa.String(40),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column("safe_result", postgresql.JSONB()),
        sa.Column("warnings", postgresql.JSONB()),
        sa.Column(
            "vision_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
            "analysis_type IN ('SYMBOL_CHART', 'MARKET_OVERVIEW')",
            name="ck_ai_mkt_analysis_type",
        ),
        sa.CheckConstraint(
            "analysis_status IN ("
            "'DRAFT_ANALYSIS','QUEUED','RUNNING','VALIDATED_ANALYSIS',"
            "'VALIDATED_WITH_WARNINGS','BLOCKED','INVALID','FAILED',"
            "'CANCELLED','SUPERSEDED')",
            name="ck_ai_mkt_analysis_status",
        ),
        sa.CheckConstraint(
            "data_classification IN "
            "('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')",
            name="ck_ai_mkt_analysis_classification",
        ),
        sa.ForeignKeyConstraint(
            ["execution_request_id"],
            ["ai.execution_request.execution_request_id"],
            name="fk_ai_market_analysis_exec_request",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("analysis_key", name="uq_ai_market_analysis_key"),
        sa.UniqueConstraint(
            "created_by",
            "idempotency_key",
            name="uq_ai_market_analysis_idempotency",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_mkt_analysis_type_status",
        "market_analysis",
        ["analysis_type", "analysis_status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_mkt_analysis_exchange_symbol",
        "market_analysis",
        ["exchange_code", "symbol"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_mkt_analysis_snapshot_key",
        "market_analysis",
        ["snapshot_key"],
        schema="ai",
    )

    op.create_table(
        "market_analysis_indicator",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("indicator_code", sa.String(40), nullable=False),
        sa.Column("indicator_version", sa.String(40), nullable=False),
        sa.Column("timeframe", sa.String(20)),
        sa.Column("value_json", postgresql.JSONB()),
        sa.Column("quality_status", sa.String(40)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["market_analysis_id"],
            ["ai.market_analysis.market_analysis_id"],
            name="fk_ai_mkt_ind_analysis",
            ondelete="CASCADE",
        ),
        schema="ai",
    )

    op.create_table(
        "market_analysis_level",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("level_type", sa.String(40), nullable=False),
        sa.Column("price", sa.String(40), nullable=False),
        sa.Column("strength", sa.String(40)),
        sa.Column("evidence", sa.String(500)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["market_analysis_id"],
            ["ai.market_analysis.market_analysis_id"],
            name="fk_ai_mkt_level_analysis",
            ondelete="CASCADE",
        ),
        schema="ai",
    )

    op.create_table(
        "market_analysis_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market_analysis_id", sa.BigInteger(), nullable=False),
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
            ["market_analysis_id"],
            ["ai.market_analysis.market_analysis_id"],
            name="fk_ai_mkt_hist_analysis",
            ondelete="CASCADE",
        ),
        schema="ai",
    )

    op.create_table(
        "market_snapshot_reference",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("source_table", sa.String(80), nullable=False),
        sa.Column("source_key", sa.String(200), nullable=False),
        sa.Column("source_version", sa.String(40)),
        sa.Column("source_hash", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["market_analysis_id"],
            ["ai.market_analysis.market_analysis_id"],
            name="fk_ai_mkt_snap_analysis",
            ondelete="CASCADE",
        ),
        schema="ai",
    )

    op.create_table(
        "market_analysis_krx_link",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["market_analysis_id"],
            ["ai.market_analysis.market_analysis_id"],
            name="fk_ai_mkt_krx_analysis",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["market.instrument.instrument_id"],
            name="fk_ai_mkt_krx_instrument",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "market_analysis_id",
            name="uq_ai_mkt_krx_link_analysis",
        ),
        schema="ai",
    )

    op.create_table(
        "market_analysis_upbit_link",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["market_analysis_id"],
            ["ai.market_analysis.market_analysis_id"],
            name="fk_ai_mkt_upbit_analysis",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["market.instrument.instrument_id"],
            name="fk_ai_mkt_upbit_instrument",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "market_analysis_id",
            name="uq_ai_mkt_upbit_link_analysis",
        ),
        schema="ai",
    )

    # CHART schema 갱신 + MARKET schema/prompt seed (idempotent)
    conn = op.get_bind()
    _seed_market_and_refresh_chart(conn)


def _seed_market_and_refresh_chart(conn: Any) -> None:
    from stock_platform.ai.prompt.seed_data import (
        CHART_ANALYSIS_RESULT_V1,
        MARKET_ANALYSIS_RESULT_V1,
        SEED_PROMPTS,
    )

    # CHART schema json 갱신 (기존 row)
    chart_js = CHART_ANALYSIS_RESULT_V1
    conn.execute(
        sa.text(
            """
            UPDATE ai.output_schema
            SET json_schema = CAST(:js AS jsonb),
                checksum = :checksum,
                updated_by = 'SEED_11_7',
                updated_at = now()
            WHERE code = 'CHART_ANALYSIS_RESULT_V1'
            """
        ),
        {
            "js": json.dumps(chart_js, ensure_ascii=False),
            "checksum": _checksum(chart_js),
        },
    )

    exists = conn.execute(
        sa.text(
            "SELECT output_schema_id FROM ai.output_schema "
            "WHERE code = 'MARKET_ANALYSIS_RESULT_V1'"
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
                    'MARKET_ANALYSIS_RESULT_V1',
                    'Market Analysis Result v1',
                    'MARKET_ANALYSIS',
                    '1.0',
                    CAST(:js AS jsonb),
                    true, false, 'ACTIVE',
                    :checksum, 'SEED', 'SEED'
                )
                RETURNING output_schema_id
                """
            ),
            {
                "js": json.dumps(MARKET_ANALYSIS_RESULT_V1, ensure_ascii=False),
                "checksum": _checksum(MARKET_ANALYSIS_RESULT_V1),
            },
        )
        schema_id = int(result.scalar_one())
    else:
        schema_id = int(exists)

    prompt_seed = next(
        (p for p in SEED_PROMPTS if p["code"] == "MARKET_ANALYSIS_BASE"),
        None,
    )
    if prompt_seed is not None:
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
                "WHERE code = 'MARKET_ANALYSIS_BASE'"
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
                    "description": "STEP 11-7 seed (DRAFT until operator activates)",
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

    # CHART prompt template 보강 (DRAFT 상태 유지)
    chart_seed = next(
        (p for p in SEED_PROMPTS if p["code"] == "CHART_ANALYSIS_BASE"),
        None,
    )
    if chart_seed:
        conn.execute(
            sa.text(
                """
                UPDATE ai.prompt_template_version v
                SET system_template = :system,
                    user_template = :user,
                    context_template = :context,
                    checksum = :checksum
                FROM ai.prompt_template t
                WHERE t.prompt_template_id = v.prompt_template_id
                  AND t.code = 'CHART_ANALYSIS_BASE'
                  AND v.version = 1
                """
            ),
            {
                "system": chart_seed["system"],
                "user": chart_seed["user"],
                "context": chart_seed.get("context") or "",
                "checksum": _text_checksum(
                    chart_seed["system"],
                    chart_seed["user"],
                    chart_seed.get("context") or "",
                ),
            },
        )


def downgrade() -> None:
    op.drop_table("market_analysis_upbit_link", schema="ai")
    op.drop_table("market_analysis_krx_link", schema="ai")
    op.drop_table("market_snapshot_reference", schema="ai")
    op.drop_table("market_analysis_history", schema="ai")
    op.drop_table("market_analysis_level", schema="ai")
    op.drop_table("market_analysis_indicator", schema="ai")
    op.drop_table("market_analysis", schema="ai")

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM ai.prompt_template_version
            WHERE prompt_template_id IN (
                SELECT prompt_template_id FROM ai.prompt_template
                WHERE code = 'MARKET_ANALYSIS_BASE'
            )
            """
        )
    )
    conn.execute(
        sa.text(
            "DELETE FROM ai.prompt_template "
            "WHERE code = 'MARKET_ANALYSIS_BASE'"
        )
    )
    conn.execute(
        sa.text(
            "DELETE FROM ai.output_schema "
            "WHERE code = 'MARKET_ANALYSIS_RESULT_V1'"
        )
    )
