"""STEP 8-5-19 — Legacy account_number schema removal.

Revision ID: g0a1b2c3d4e5
Revises: f9a0b1c2d3e4
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- position_limit: UBA/Paper FK, drop account_number UK ---
    op.add_column(
        "position_limit",
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "position_limit",
        sa.Column("paper_account_id", sa.BigInteger(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "position_limit",
        sa.Column(
            "account_scope_type",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'UNKNOWN'"),
        ),
        schema="operation",
    )
    op.add_column(
        "position_limit",
        sa.Column("masked_account_ref", sa.String(40), nullable=True),
        schema="operation",
    )

    # 기존 행: account_number → LEGACY_ORPHAN (자동 UBA 연결 금지)
    op.execute(
        """
        UPDATE operation.position_limit
        SET account_scope_type = 'LEGACY_ORPHAN',
            masked_account_ref = CASE
              WHEN length(account_number) > 4
              THEN repeat('*', greatest(length(account_number) - 4, 0))
                   || right(account_number, 4)
              ELSE '****'
            END
        WHERE user_broker_account_id IS NULL
          AND paper_account_id IS NULL
        """
    )

    op.drop_constraint(
        "uq_position_limit_scope",
        "position_limit",
        schema="operation",
        type_="unique",
    )
    op.drop_column("position_limit", "account_number", schema="operation")

    op.create_check_constraint(
        "ck_position_limit_exactly_one_scope",
        "position_limit",
        """
        (
          (user_broker_account_id IS NOT NULL AND paper_account_id IS NULL
           AND account_scope_type = 'LIVE')
          OR
          (user_broker_account_id IS NULL AND paper_account_id IS NOT NULL
           AND account_scope_type = 'PAPER')
          OR
          (user_broker_account_id IS NULL AND paper_account_id IS NULL
           AND account_scope_type = 'LEGACY_ORPHAN')
        )
        """,
        schema="operation",
    )
    op.create_index(
        "uq_position_limit_uba_symbol",
        "position_limit",
        ["user_broker_account_id", "exchange_code", "symbol"],
        unique=True,
        schema="operation",
        postgresql_where=sa.text("user_broker_account_id IS NOT NULL"),
    )
    op.create_index(
        "uq_position_limit_paper_symbol",
        "position_limit",
        ["paper_account_id", "exchange_code", "symbol"],
        unique=True,
        schema="operation",
        postgresql_where=sa.text("paper_account_id IS NOT NULL"),
    )

    # --- risk_event: UBA/Paper + masked, drop account_number ---
    op.add_column(
        "risk_event",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "risk_event",
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "risk_event",
        sa.Column("paper_account_id", sa.BigInteger(), nullable=True),
        schema="operation",
    )
    op.add_column(
        "risk_event",
        sa.Column("correlation_id", sa.String(64), nullable=True),
        schema="operation",
    )
    op.add_column(
        "risk_event",
        sa.Column("masked_account_ref", sa.String(40), nullable=True),
        schema="operation",
    )
    op.add_column(
        "risk_event",
        sa.Column(
            "account_scope_type",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'UNKNOWN'"),
        ),
        schema="operation",
    )

    # UBA:/PAPER: 토큰 백필
    op.execute(
        """
        UPDATE operation.risk_event
        SET user_broker_account_id = NULLIF(
              regexp_replace(account_number, '^UBA:', ''), ''
            )::bigint,
            account_scope_type = 'LIVE',
            masked_account_ref = account_number
        WHERE account_number LIKE 'UBA:%'
          AND account_number ~ '^UBA:[0-9]+$'
        """
    )
    op.execute(
        """
        UPDATE operation.risk_event
        SET paper_account_id = NULLIF(
              regexp_replace(account_number, '^PAPER:', ''), ''
            )::bigint,
            account_scope_type = 'PAPER',
            masked_account_ref = account_number
        WHERE account_number LIKE 'PAPER:%'
          AND account_number ~ '^PAPER:[0-9]+$'
        """
    )
    op.execute(
        """
        UPDATE operation.risk_event
        SET account_scope_type = 'LEGACY_ORPHAN',
            masked_account_ref = CASE
              WHEN length(account_number) > 4
              THEN repeat('*', greatest(length(account_number) - 4, 0))
                   || right(account_number, 4)
              ELSE '****'
            END
        WHERE user_broker_account_id IS NULL
          AND paper_account_id IS NULL
        """
    )

    op.drop_column("risk_event", "account_number", schema="operation")

    op.create_check_constraint(
        "ck_risk_event_account_scope",
        "risk_event",
        """
        (
          (user_broker_account_id IS NOT NULL AND paper_account_id IS NULL
           AND account_scope_type = 'LIVE')
          OR
          (user_broker_account_id IS NULL AND paper_account_id IS NOT NULL
           AND account_scope_type = 'PAPER')
          OR
          (user_broker_account_id IS NULL AND paper_account_id IS NULL
           AND account_scope_type IN ('LEGACY_ORPHAN', 'SYSTEM'))
        )
        """,
        schema="operation",
    )
    op.create_index(
        "ix_risk_event_uba_created",
        "risk_event",
        ["user_broker_account_id", "created_at"],
        schema="operation",
    )
    op.create_index(
        "ix_risk_event_paper_created",
        "risk_event",
        ["paper_account_id", "created_at"],
        schema="operation",
    )
    op.create_index(
        "ix_risk_event_correlation",
        "risk_event",
        ["correlation_id"],
        schema="operation",
    )

    # --- account_daily_loss (Method A: LIVE/Paper 단일 테이블) ---
    op.create_table(
        "account_daily_loss",
        sa.Column(
            "account_daily_loss_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("account_scope_type", sa.String(20), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("paper_account_id", sa.BigInteger(), nullable=True),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column(
            "currency_code",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'KRW'"),
        ),
        sa.Column(
            "market_code",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'KRX'"),
        ),
        sa.Column(
            "realized_profit_loss",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "unrealized_profit_loss",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "combined_profit_loss",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "current_loss_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "loss_limit_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "status_code",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'SAFE'"),
        ),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            """
            (
              (user_broker_account_id IS NOT NULL AND paper_account_id IS NULL
               AND account_scope_type = 'LIVE')
              OR
              (user_broker_account_id IS NULL AND paper_account_id IS NOT NULL
               AND account_scope_type = 'PAPER')
            )
            """,
            name="ck_account_daily_loss_exactly_one_scope",
        ),
        schema="operation",
    )
    op.create_index(
        "uq_account_daily_loss_uba",
        "account_daily_loss",
        [
            "user_broker_account_id",
            "trading_date",
            "currency_code",
            "market_code",
        ],
        unique=True,
        schema="operation",
        postgresql_where=sa.text("user_broker_account_id IS NOT NULL"),
    )
    op.create_index(
        "uq_account_daily_loss_paper",
        "account_daily_loss",
        [
            "paper_account_id",
            "trading_date",
            "currency_code",
            "market_code",
        ],
        unique=True,
        schema="operation",
        postgresql_where=sa.text("paper_account_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("account_daily_loss", schema="operation")

    op.drop_index(
        "ix_risk_event_correlation",
        table_name="risk_event",
        schema="operation",
    )
    op.drop_index(
        "ix_risk_event_paper_created",
        table_name="risk_event",
        schema="operation",
    )
    op.drop_index(
        "ix_risk_event_uba_created",
        table_name="risk_event",
        schema="operation",
    )
    op.drop_constraint(
        "ck_risk_event_account_scope",
        "risk_event",
        schema="operation",
        type_="check",
    )
    op.add_column(
        "risk_event",
        sa.Column(
            "account_number",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'UNKNOWN'"),
        ),
        schema="operation",
    )
    op.execute(
        """
        UPDATE operation.risk_event
        SET account_number = COALESCE(
          CASE WHEN user_broker_account_id IS NOT NULL
               THEN 'UBA:' || user_broker_account_id::text
               WHEN paper_account_id IS NOT NULL
               THEN 'PAPER:' || paper_account_id::text
               ELSE masked_account_ref END,
          'UNKNOWN'
        )
        """
    )
    op.alter_column(
        "risk_event",
        "account_number",
        schema="operation",
        server_default=None,
    )
    op.drop_column("risk_event", "account_scope_type", schema="operation")
    op.drop_column("risk_event", "masked_account_ref", schema="operation")
    op.drop_column("risk_event", "correlation_id", schema="operation")
    op.drop_column("risk_event", "paper_account_id", schema="operation")
    op.drop_column("risk_event", "user_broker_account_id", schema="operation")
    op.drop_column("risk_event", "user_id", schema="operation")

    op.drop_index(
        "uq_position_limit_paper_symbol",
        table_name="position_limit",
        schema="operation",
    )
    op.drop_index(
        "uq_position_limit_uba_symbol",
        table_name="position_limit",
        schema="operation",
    )
    op.drop_constraint(
        "ck_position_limit_exactly_one_scope",
        "position_limit",
        schema="operation",
        type_="check",
    )
    op.add_column(
        "position_limit",
        sa.Column(
            "account_number",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'UNKNOWN'"),
        ),
        schema="operation",
    )
    op.execute(
        """
        UPDATE operation.position_limit
        SET account_number = COALESCE(
          CASE WHEN user_broker_account_id IS NOT NULL
               THEN 'UBA:' || user_broker_account_id::text
               WHEN paper_account_id IS NOT NULL
               THEN 'PAPER:' || paper_account_id::text
               ELSE masked_account_ref END,
          'UNKNOWN'
        )
        """
    )
    op.alter_column(
        "position_limit",
        "account_number",
        schema="operation",
        server_default=None,
    )
    op.create_unique_constraint(
        "uq_position_limit_scope",
        "position_limit",
        ["broker_code", "account_number", "exchange_code", "symbol"],
        schema="operation",
    )
    op.drop_column("position_limit", "masked_account_ref", schema="operation")
    op.drop_column("position_limit", "account_scope_type", schema="operation")
    op.drop_column("position_limit", "paper_account_id", schema="operation")
    op.drop_column(
        "position_limit", "user_broker_account_id", schema="operation"
    )
