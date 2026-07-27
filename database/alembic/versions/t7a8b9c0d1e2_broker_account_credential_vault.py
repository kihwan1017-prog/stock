"""Broker account credential vault (STEP 8-5-2).

Revision ID: t7a8b9c0d1e2
Revises: s6f7a8b9c0d1
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "t7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "s6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broker_account_credential",
        sa.Column(
            "broker_account_credential_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("broker_code", sa.String(20), nullable=False),
        sa.Column(
            "credential_type",
            sa.String(40),
            nullable=False,
            server_default="BROKER_API",
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
            "payload_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "verification_status",
            sa.String(30),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("verification_message", sa.Text(), nullable=True),
        sa.Column("masked_identifier", sa.String(80), nullable=True),
        sa.Column(
            "last_verified_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
            ["user_broker_account_id"],
            ["trading.user_broker_account.user_broker_account_id"],
            name="fk_broker_cred_uba",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "broker_code IN ('KIWOOM', 'UPBIT')",
            name="ck_broker_cred_broker_code",
        ),
        sa.CheckConstraint(
            "credential_type IN ('BROKER_API')",
            name="ck_broker_cred_type",
        ),
        sa.CheckConstraint(
            "verification_status IN ("
            "'PENDING','VERIFIED','FAILED','REVOKED')",
            name="ck_broker_cred_verification",
        ),
        sa.CheckConstraint(
            "encryption_algorithm = 'AES-256-GCM'",
            name="ck_broker_cred_algorithm",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_broker_cred_uba",
        "broker_account_credential",
        ["user_broker_account_id"],
        schema="trading",
    )
    # 계좌당 활성 Credential 1개 (BROKER_API)
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_broker_cred_active_uba_type
            ON trading.broker_account_credential (
                user_broker_account_id, credential_type
            )
            WHERE is_active = true
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS trading.uq_broker_cred_active_uba_type"
        )
    )
    op.drop_index(
        "ix_broker_cred_uba",
        table_name="broker_account_credential",
        schema="trading",
    )
    op.drop_table("broker_account_credential", schema="trading")
