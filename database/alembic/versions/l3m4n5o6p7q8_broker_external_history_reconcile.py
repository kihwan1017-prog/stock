"""Broker external order/trade history — baseline reconciliation after k2

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7

Provenance:
- Quarantined WIP h1a2b3c4d5e6 (j4 branch) 스키마를 k2 head 이후 graph에 편입
- h1a를 versions/에 복원하거나 parent로 사용하지 않음
- 기존 운영 DB에 테이블이 이미 있으면 create skip (idempotent)
- 데이터 DML 없음 / DROP 없음
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

revision: str = "l3m4n5o6p7q8"
down_revision: Union[str, Sequence[str], None] = "k2l3m4n5o6p7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "operation"
_ORDER_TABLE = "broker_external_order_history"
_TRADE_TABLE = "broker_external_trade_history"


def _connection() -> Connection:
    return op.get_bind()


def _has_table(table_name: str) -> bool:
    return inspect(_connection()).has_table(table_name, schema=_SCHEMA)


def _index_names(table_name: str) -> set[str]:
    return {
        str(ix.get("name"))
        for ix in inspect(_connection()).get_indexes(table_name, schema=_SCHEMA)
        if ix.get("name")
    }


def _unique_constraint_names(table_name: str) -> set[str]:
    return {
        str(uc.get("name"))
        for uc in inspect(_connection()).get_unique_constraints(
            table_name, schema=_SCHEMA
        )
        if uc.get("name")
    }


def _ensure_schema() -> None:
    op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))


def _create_order_history_table() -> None:
    op.create_table(
        _ORDER_TABLE,
        sa.Column(
            "broker_external_order_history_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("broker_code", sa.String(30), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("external_order_id", sa.String(100), nullable=False),
        sa.Column("external_order_id_masked", sa.String(40), nullable=True),
        sa.Column("market_code", sa.String(40), nullable=True),
        sa.Column("side_code", sa.String(10), nullable=True),
        sa.Column("order_type_code", sa.String(30), nullable=True),
        sa.Column("order_price", sa.Numeric(28, 8), nullable=True),
        sa.Column("requested_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("executed_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("remaining_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("paid_fee", sa.Numeric(28, 8), nullable=True),
        sa.Column("locked_amount", sa.Numeric(28, 8), nullable=True),
        sa.Column("external_status", sa.String(40), nullable=True),
        sa.Column(
            "external_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "external_done_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "raw_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "import_policy",
            sa.String(60),
            nullable=False,
            server_default="PRESERVE_REMOTE_HISTORY",
        ),
        sa.Column("source_conflict_id", sa.BigInteger(), nullable=True),
        sa.Column("imported_by", sa.String(100), nullable=True),
        sa.Column(
            "imported_at",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "broker_code",
            "external_order_id",
            name="uq_broker_ext_order_broker_uuid",
        ),
        schema=_SCHEMA,
    )


def _create_trade_history_table() -> None:
    op.create_table(
        _TRADE_TABLE,
        sa.Column(
            "broker_external_trade_history_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("broker_code", sa.String(30), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("external_trade_id", sa.String(100), nullable=False),
        sa.Column("external_order_id", sa.String(100), nullable=False),
        sa.Column("market_code", sa.String(40), nullable=True),
        sa.Column("side_code", sa.String(10), nullable=True),
        sa.Column("trade_price", sa.Numeric(28, 8), nullable=True),
        sa.Column("trade_volume", sa.Numeric(28, 8), nullable=True),
        sa.Column("funds", sa.Numeric(28, 8), nullable=True),
        sa.Column("fee", sa.Numeric(28, 8), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "raw_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("source_conflict_id", sa.BigInteger(), nullable=True),
        sa.Column("imported_by", sa.String(100), nullable=True),
        sa.Column(
            "imported_at",
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
        sa.UniqueConstraint(
            "broker_code",
            "external_trade_id",
            name="uq_broker_ext_trade_broker_uuid",
        ),
        schema=_SCHEMA,
    )


def _ensure_order_indexes() -> None:
    existing = _index_names(_ORDER_TABLE)
    unique_names = _unique_constraint_names(_ORDER_TABLE)

    if "ix_broker_ext_order_uba" not in existing:
        op.create_index(
            "ix_broker_ext_order_uba",
            _ORDER_TABLE,
            ["user_broker_account_id"],
            schema=_SCHEMA,
        )
    if "ix_broker_ext_order_conflict" not in existing:
        op.create_index(
            "ix_broker_ext_order_conflict",
            _ORDER_TABLE,
            ["source_conflict_id"],
            schema=_SCHEMA,
        )
    # UniqueConstraint는 create_table 경로에서 생성됨.
    # 기존 테이블에만 빠진 경우 CREATE UNIQUE INDEX IF NOT EXISTS 로 보강.
    if "uq_broker_ext_order_broker_uuid" not in unique_names and (
        "uq_broker_ext_order_broker_uuid" not in existing
    ):
        op.execute(
            sa.text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS uq_broker_ext_order_broker_uuid "
                f"ON {_SCHEMA}.{_ORDER_TABLE} (broker_code, external_order_id)"
            )
        )


def _ensure_trade_indexes() -> None:
    existing = _index_names(_TRADE_TABLE)
    unique_names = _unique_constraint_names(_TRADE_TABLE)

    if "ix_broker_ext_trade_order" not in existing:
        op.create_index(
            "ix_broker_ext_trade_order",
            _TRADE_TABLE,
            ["external_order_id"],
            schema=_SCHEMA,
        )
    if "uq_broker_ext_trade_broker_uuid" not in unique_names and (
        "uq_broker_ext_trade_broker_uuid" not in existing
    ):
        op.execute(
            sa.text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS uq_broker_ext_trade_broker_uuid "
                f"ON {_SCHEMA}.{_TRADE_TABLE} (broker_code, external_trade_id)"
            )
        )


def upgrade() -> None:
    _ensure_schema()

    if not _has_table(_ORDER_TABLE):
        _create_order_history_table()
    _ensure_order_indexes()

    if not _has_table(_TRADE_TABLE):
        _create_trade_history_table()
    _ensure_trade_indexes()


def downgrade() -> None:
    # 운영 history row 보존 — table DROP 금지 (irreversible)
    raise NotImplementedError(
        "l3m4n5o6p7q8 downgrade is irreversible: "
        "operation.broker_external_* history tables must not be auto-dropped"
    )
