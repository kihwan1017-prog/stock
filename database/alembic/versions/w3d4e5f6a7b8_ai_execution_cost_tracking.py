"""AI Execution request/run/result/cost tracking (STEP 11-5).

Revision ID: w3d4e5f6a7b8
Revises: v2c3d4e5f6a7
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "v2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")

    op.create_table(
        "execution_request",
        sa.Column(
            "execution_request_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("task_type", sa.String(60), nullable=False),
        sa.Column(
            "status", sa.String(40), nullable=False, server_default="DRAFT"
        ),
        sa.Column(
            "execution_mode",
            sa.String(20),
            nullable=False,
            server_default="MOCK",
        ),
        sa.Column("provider_code", sa.String(40)),
        sa.Column("provider_configuration_id", sa.BigInteger()),
        sa.Column("requested_model", sa.String(200)),
        sa.Column("prompt_template_id", sa.BigInteger()),
        sa.Column("prompt_version_id", sa.BigInteger()),
        sa.Column("output_schema_id", sa.BigInteger()),
        sa.Column("policy_ids", postgresql.JSONB()),
        sa.Column("input_meta", postgresql.JSONB()),
        sa.Column("input_hash", sa.String(64)),
        sa.Column("rendered_prompt_hash", sa.String(64)),
        sa.Column(
            "max_tokens", sa.Integer(), nullable=False, server_default="256"
        ),
        sa.Column(
            "temperature", sa.Float(), nullable=False, server_default="0.2"
        ),
        sa.Column(
            "timeout_sec", sa.Float(), nullable=False, server_default="30"
        ),
        sa.Column(
            "fallback_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "retry_max", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("budget_limit", sa.Float()),
        sa.Column("estimated_max_cost", sa.Float()),
        sa.Column(
            "currency", sa.String(8), nullable=False, server_default="USD"
        ),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("approved_by", sa.String(100)),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("lease_owner", sa.String(100)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("queued_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "lock_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("sanitized_error", sa.String(500)),
        sa.Column("input_payload_sanitized", postgresql.JSONB()),
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
        sa.UniqueConstraint("request_key", name="uq_ai_exec_request_key"),
        sa.UniqueConstraint(
            "requested_by",
            "idempotency_key",
            name="uq_ai_exec_idempotency",
        ),
        sa.CheckConstraint(
            "execution_mode IN ('DRY_RUN','MOCK','EXTERNAL')",
            name="ck_ai_exec_mode",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_exec_request_status",
        "execution_request",
        ["status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_exec_request_created",
        "execution_request",
        ["created_at"],
        schema="ai",
    )

    op.create_table(
        "execution_run",
        sa.Column(
            "execution_run_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("execution_request_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("provider_code", sa.String(40), nullable=False),
        sa.Column("provider_configuration_id", sa.BigInteger()),
        sa.Column(
            "model", sa.String(200), nullable=False, server_default=""
        ),
        sa.Column(
            "status", sa.String(40), nullable=False, server_default="CREATED"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("estimated_cost", sa.Float()),
        sa.Column("actual_cost", sa.Float()),
        sa.Column(
            "currency", sa.String(8), nullable=False, server_default="USD"
        ),
        sa.Column(
            "cost_calculation_status",
            sa.String(40),
            nullable=False,
            server_default="NOT_APPLICABLE",
        ),
        sa.Column("pricing_version", sa.String(40)),
        sa.Column("finish_reason", sa.String(40)),
        sa.Column("provider_request_id", sa.String(120)),
        sa.Column("retry_reason", sa.String(200)),
        sa.Column("fallback_reason", sa.String(200)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("sanitized_error", sa.String(500)),
        sa.Column("circuit_state", sa.String(40)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["execution_request_id"],
            ["ai.execution_request.execution_request_id"],
            name="fk_ai_exec_run_request",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "execution_request_id",
            "attempt_no",
            name="uq_ai_exec_run_attempt",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_exec_run_request",
        "execution_run",
        ["execution_request_id"],
        schema="ai",
    )

    op.create_table(
        "execution_result",
        sa.Column(
            "execution_result_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("execution_request_id", sa.BigInteger(), nullable=False),
        sa.Column("execution_run_id", sa.BigInteger()),
        sa.Column("validation_status", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(20)),
        sa.Column("result_payload", postgresql.JSONB()),
        sa.Column("result_hash", sa.String(64)),
        sa.Column("confidence", sa.Float()),
        sa.Column("reasoning_summary", sa.Text()),
        sa.Column("warnings", postgresql.JSONB()),
        sa.Column("citations", postgresql.JSONB()),
        sa.Column("policy_findings", postgresql.JSONB()),
        sa.Column("data_quality", postgresql.JSONB()),
        sa.Column(
            "raw_response_retained",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["execution_request_id"],
            ["ai.execution_request.execution_request_id"],
            name="fk_ai_exec_result_request",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "execution_request_id", name="uq_ai_exec_result_request"
        ),
        schema="ai",
    )

    op.create_table(
        "execution_event",
        sa.Column(
            "execution_event_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("execution_request_id", sa.BigInteger(), nullable=False),
        sa.Column("execution_run_id", sa.BigInteger()),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("previous_status", sa.String(40)),
        sa.Column("new_status", sa.String(40)),
        sa.Column("detail_sanitized", postgresql.JSONB()),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["execution_request_id"],
            ["ai.execution_request.execution_request_id"],
            name="fk_ai_exec_event_request",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_exec_event_request",
        "execution_event",
        ["execution_request_id"],
        schema="ai",
    )

    op.create_table(
        "provider_pricing",
        sa.Column(
            "provider_pricing_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("provider_code", sa.String(40), nullable=False),
        sa.Column("model_pattern", sa.String(120), nullable=False),
        sa.Column(
            "currency", sa.String(8), nullable=False, server_default="USD"
        ),
        sa.Column("input_price_per_1m_tokens", sa.Float(), nullable=False),
        sa.Column("output_price_per_1m_tokens", sa.Float(), nullable=False),
        sa.Column(
            "pricing_version",
            sa.String(40),
            nullable=False,
            server_default="SEED_TEST",
        ),
        sa.Column(
            "source", sa.String(40), nullable=False, server_default="OPERATOR"
        ),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_provider_pricing_code",
        "provider_pricing",
        ["provider_code"],
        schema="ai",
    )

    # Seed: 테스트용 예시 가격 (실제 최신 요금 단정 금지)
    op.execute(
        """
        INSERT INTO ai.provider_pricing (
            provider_code, model_pattern, currency,
            input_price_per_1m_tokens, output_price_per_1m_tokens,
            pricing_version, source
        ) VALUES
        ('openai', 'gpt-4o-mini*', 'USD', 0.15, 0.60, 'SEED_TEST', 'OPERATOR'),
        ('claude', 'claude*', 'USD', 3.0, 15.0, 'SEED_TEST', 'OPERATOR'),
        ('gemini', 'gemini*', 'USD', 0.10, 0.40, 'SEED_TEST', 'OPERATOR')
        """
    )


def downgrade() -> None:
    op.drop_table("provider_pricing", schema="ai")
    op.drop_table("execution_event", schema="ai")
    op.drop_table("execution_result", schema="ai")
    op.drop_table("execution_run", schema="ai")
    op.drop_table("execution_request", schema="ai")
