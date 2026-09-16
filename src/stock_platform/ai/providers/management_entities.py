"""STEP 11-3 — AI Provider Configuration / Credential ORM."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base

PROVIDER_CODES = frozenset(
    {
        "mock",
        "openai",
        "claude",
        "gemini",
        "ollama",
        "openai_compatible",
    }
)

# Secret 불필요 Provider
NO_SECRET_PROVIDERS = frozenset({"mock", "ollama"})
# Credential 선택적
OPTIONAL_SECRET_PROVIDERS = frozenset({"openai_compatible"})

CREDENTIAL_STATUSES = frozenset(
    {"PENDING", "VERIFIED", "INVALID", "REVOKED", "EXPIRED"}
)

HEADER_ALLOWLIST = frozenset(
    {
        "x-api-key",
        "x-request-id",
        "x-correlation-id",
        "openai-organization",
        "openai-project",
        "anthropic-version",
    }
)
HEADER_DENYLIST = frozenset(
    {
        "cookie",
        "host",
        "content-length",
        "connection",
        "transfer-encoding",
        "upgrade",
    }
)


class AIProviderConfigurationEntity(Base):
    __tablename__ = "provider_configuration"
    __table_args__ = {"schema": "ai"}

    provider_configuration_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("100")
    )
    model: Mapped[str] = mapped_column(
        String(200), nullable=False, server_default=text("''")
    )
    endpoint: Mapped[str] = mapped_column(
        String(500), nullable=False, server_default=text("''")
    )
    timeout_sec: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("30")
    )
    retry_max: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("2")
    )
    max_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1024")
    )
    temperature: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0.2")
    )
    capability_overrides: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    health_check_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    health_check_interval_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("60")
    )
    config_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    runtime_loaded_version: Mapped[int | None] = mapped_column(Integer)
    reload_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_reload_result: Mapped[str | None] = mapped_column(String(40))
    last_reload_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by: Mapped[str | None] = mapped_column(String(100))
    updated_by: Mapped[str | None] = mapped_column(String(100))


class AIProviderCredentialEntity(Base):
    __tablename__ = "provider_credential"
    __table_args__ = {"schema": "ai"}

    provider_credential_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    provider_configuration_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.provider_configuration.provider_configuration_id",
            ondelete="CASCADE",
            name="fk_ai_provider_credential_config",
        ),
        nullable=False,
    )
    credential_type: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'API_KEY'")
    )
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    nonce_b64: Mapped[str] = mapped_column(String(64), nullable=False)
    encryption_algorithm: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'AES-256-GCM'")
    )
    key_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'PENDING'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    masked_identifier: Mapped[str | None] = mapped_column(String(80))
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by: Mapped[str | None] = mapped_column(String(100))
    updated_by: Mapped[str | None] = mapped_column(String(100))


class AIProviderConfigurationHistoryEntity(Base):
    __tablename__ = "provider_configuration_history"
    __table_args__ = {"schema": "ai"}

    provider_configuration_history_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    provider_configuration_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.provider_configuration.provider_configuration_id",
            ondelete="CASCADE",
            name="fk_ai_provider_history_config",
        ),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    changed_by: Mapped[str | None] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(String(500))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
