"""AI Provider configuration & credential vault (STEP 11-3).

Revision ID: u1b2c3d4e5f6
Revises: t0a1b2c3d4e5
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "u1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "t0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROVIDER_CODES = (
    "mock",
    "openai",
    "claude",
    "gemini",
    "ollama",
    "openai_compatible",
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")

    op.create_table(
        "provider_configuration",
        sa.Column(
            "provider_configuration_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("provider_code", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
        sa.Column("model", sa.String(200), nullable=False, server_default=""),
        sa.Column("endpoint", sa.String(500), nullable=False, server_default=""),
        sa.Column(
            "timeout_sec",
            sa.Float(),
            nullable=False,
            server_default="30",
        ),
        sa.Column(
            "retry_max",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
        sa.Column(
            "max_tokens",
            sa.Integer(),
            nullable=False,
            server_default="1024",
        ),
        sa.Column(
            "temperature",
            sa.Float(),
            nullable=False,
            server_default="0.2",
        ),
        sa.Column(
            "capability_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "health_check_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "health_check_interval_sec",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
        sa.Column(
            "config_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "runtime_loaded_version",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "reload_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_reload_result", sa.String(40), nullable=True),
        sa.Column("last_reload_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("updated_by", sa.String(100), nullable=True),
        sa.UniqueConstraint(
            "provider_code",
            name="uq_ai_provider_configuration_code",
        ),
        sa.CheckConstraint(
            "provider_code IN ("
            + ", ".join(f"'{c}'" for c in PROVIDER_CODES)
            + ")",
            name="ck_ai_provider_code",
        ),
        sa.CheckConstraint(
            "timeout_sec >= 1 AND timeout_sec <= 600",
            name="ck_ai_provider_timeout",
        ),
        sa.CheckConstraint(
            "retry_max >= 0 AND retry_max <= 10",
            name="ck_ai_provider_retry",
        ),
        sa.CheckConstraint(
            "max_tokens >= 1 AND max_tokens <= 128000",
            name="ck_ai_provider_max_tokens",
        ),
        sa.CheckConstraint(
            "temperature >= 0 AND temperature <= 2",
            name="ck_ai_provider_temperature",
        ),
        sa.CheckConstraint(
            "NOT (is_default = true AND enabled = false)",
            name="ck_ai_provider_default_requires_enabled",
        ),
        schema="ai",
    )
    # default Provider 최대 1개 (enabled+default)
    op.execute(
        """
        CREATE UNIQUE INDEX uq_ai_provider_single_default
        ON ai.provider_configuration ((is_default))
        WHERE is_default = true
        """
    )
    op.create_index(
        "ix_ai_provider_configuration_enabled",
        "provider_configuration",
        ["enabled"],
        schema="ai",
    )

    op.create_table(
        "provider_credential",
        sa.Column(
            "provider_credential_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column(
            "provider_configuration_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "credential_type",
            sa.String(40),
            nullable=False,
            server_default="API_KEY",
        ),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("nonce_b64", sa.String(64), nullable=False),
        sa.Column(
            "encryption_algorithm",
            sa.String(40),
            nullable=False,
            server_default="AES-256-GCM",
        ),
        sa.Column(
            "key_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("masked_identifier", sa.String(80), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("updated_by", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(
            ["provider_configuration_id"],
            ["ai.provider_configuration.provider_configuration_id"],
            name="fk_ai_provider_credential_config",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','VERIFIED','INVALID','REVOKED','EXPIRED')",
            name="ck_ai_provider_credential_status",
        ),
        sa.CheckConstraint(
            "credential_type IN ('API_KEY','API_KEY_OPTIONAL','NONE')",
            name="ck_ai_provider_credential_type",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_provider_credential_config",
        "provider_credential",
        ["provider_configuration_id"],
        schema="ai",
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_ai_provider_credential_active
        ON ai.provider_credential (provider_configuration_id)
        WHERE is_active = true
        """
    )

    op.create_table(
        "provider_configuration_history",
        sa.Column(
            "provider_configuration_history_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("provider_configuration_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column(
            "previous_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "new_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("changed_by", sa.String(100), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_configuration_id"],
            ["ai.provider_configuration.provider_configuration_id"],
            name="fk_ai_provider_history_config",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_provider_history_config",
        "provider_configuration_history",
        ["provider_configuration_id"],
        schema="ai",
    )

    # Seed: Mock only enabled+default (자동 외부 Provider enable 없음)
    op.execute(
        """
        INSERT INTO ai.provider_configuration (
            provider_code, display_name, enabled, is_default, priority,
            model, endpoint, timeout_sec, retry_max, max_tokens, temperature,
            created_by, updated_by
        ) VALUES
        ('mock', 'Mock Provider', true, true, 10,
         'mock-v1', '', 5, 1, 256, 0.2, 'SEED', 'SEED'),
        ('openai', 'OpenAI', false, false, 20,
         'gpt-4o-mini', 'https://api.openai.com/v1', 30, 2, 1024, 0.2, 'SEED', 'SEED'),
        ('claude', 'Claude (Anthropic)', false, false, 30,
         'claude-3-5-sonnet-latest', 'https://api.anthropic.com', 30, 2, 1024, 0.2, 'SEED', 'SEED'),
        ('gemini', 'Gemini', false, false, 40,
         'gemini-2.0-flash', 'https://generativelanguage.googleapis.com', 30, 2, 1024, 0.2, 'SEED', 'SEED'),
        ('ollama', 'Ollama', false, false, 50,
         'qwen3.5:4b', 'http://127.0.0.1:11434', 120, 1, 1024, 0.2, 'SEED', 'SEED'),
        ('openai_compatible', 'OpenAI Compatible', false, false, 60,
         'local-model', '', 30, 2, 1024, 0.2, 'SEED', 'SEED')
        """
    )


def downgrade() -> None:
    op.drop_table("provider_configuration_history", schema="ai")
    op.execute("DROP INDEX IF EXISTS ai.uq_ai_provider_credential_active")
    op.drop_table("provider_credential", schema="ai")
    op.execute("DROP INDEX IF EXISTS ai.uq_ai_provider_single_default")
    op.drop_table("provider_configuration", schema="ai")
