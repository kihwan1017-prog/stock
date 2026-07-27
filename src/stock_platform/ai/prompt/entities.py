"""STEP 11-4 — Prompt / Schema / Policy ORM."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class AIPromptTemplateEntity(Base):
    __tablename__ = "prompt_template"
    __table_args__ = (
        UniqueConstraint("code", name="uq_ai_prompt_template_code"),
        {"schema": "ai"},
    )

    prompt_template_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    task_type: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )
    active_version_id: Mapped[int | None] = mapped_column(BigInteger)
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AIPromptTemplateVersionEntity(Base):
    __tablename__ = "prompt_template_version"
    __table_args__ = (
        UniqueConstraint(
            "prompt_template_id",
            "version",
            name="uq_ai_prompt_template_version",
        ),
        {"schema": "ai"},
    )

    prompt_template_version_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    prompt_template_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "ai.prompt_template.prompt_template_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system_template: Mapped[str] = mapped_column(Text, nullable=False)
    user_template: Mapped[str] = mapped_column(Text, nullable=False)
    context_template: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    safety_instruction: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    output_instruction: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    variable_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    required_capabilities: Mapped[list[Any] | None] = mapped_column(JSONB)
    output_schema_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ai.output_schema.output_schema_id", ondelete="RESTRICT"),
    )
    policy_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ai.policy_definition.policy_definition_id", ondelete="RESTRICT"),
    )
    change_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIOutputSchemaEntity(Base):
    __tablename__ = "output_schema"
    __table_args__ = (
        UniqueConstraint("code", name="uq_ai_output_schema_code"),
        {"schema": "ai"},
    )

    output_schema_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    task_type: Mapped[str] = mapped_column(String(60), nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="1.0"
    )
    json_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    strict_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    additional_properties_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    compatibility: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="BREAKING"
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AIPolicyDefinitionEntity(Base):
    __tablename__ = "policy_definition"
    __table_args__ = (
        UniqueConstraint(
            "code", "version", name="uq_ai_policy_code_version"
        ),
        {"schema": "ai"},
    )

    policy_definition_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    policy_type: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="HIGH"
    )
    enforcement_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="BLOCK"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )
    is_core: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    change_reason: Mapped[str] = mapped_column(
        String(500), nullable=False, server_default=""
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AIPromptChangeHistoryEntity(Base):
    __tablename__ = "prompt_change_history"
    __table_args__ = {"schema": "ai"}

    prompt_change_history_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    prompt_template_id: Mapped[int | None] = mapped_column(BigInteger)
    prompt_version_id: Mapped[int | None] = mapped_column(BigInteger)
    output_schema_id: Mapped[int | None] = mapped_column(BigInteger)
    policy_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    changed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
