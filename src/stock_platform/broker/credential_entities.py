"""STEP 8-5-2 — Broker Account Credential Entity."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class BrokerAccountCredentialEntity(Base):
    """UBA별 암호화 Credential (평문 Secret 미저장)."""

    __tablename__ = "broker_account_credential"
    __table_args__ = {"schema": "trading"}

    broker_account_credential_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    user_broker_account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "trading.user_broker_account.user_broker_account_id",
            ondelete="CASCADE",
            name="fk_broker_cred_uba",
        ),
        nullable=False,
        index=True,
    )
    broker_code: Mapped[str] = mapped_column(String(20), nullable=False)
    # 현재는 BROKER_API 단일 타입 (키움/업비트 장기 키)
    credential_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'BROKER_API'"),
    )
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    nonce_b64: Mapped[str] = mapped_column(String(64), nullable=False)
    encryption_algorithm: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'AES-256-GCM'"),
    )
    key_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    payload_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # PENDING | VERIFIED | FAILED | REVOKED
    verification_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    verification_message: Mapped[str | None] = mapped_column(Text)
    # 마스킹 식별자만 (예: app_key 앞 4자, access_key 앞 4자)
    masked_identifier: Mapped[str | None] = mapped_column(String(80))
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by: Mapped[str | None] = mapped_column(String(100))
    updated_by: Mapped[str | None] = mapped_column(String(100))
