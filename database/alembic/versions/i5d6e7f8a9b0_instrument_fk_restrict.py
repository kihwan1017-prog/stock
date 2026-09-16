"""P1 — instrument CASCADE → RESTRICT (대량삭제 방지)

Revision ID: i5d6e7f8a9b0
Revises: h4c5d6e7f8a9
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "i5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "h4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _swap_fk(
    *,
    table: str,
    schema: str,
    old_name: str,
    new_name: str,
    columns: list[str],
    ref_schema: str,
    ref_table: str,
    ref_columns: list[str],
    ondelete: str,
) -> None:
    op.drop_constraint(old_name, table, schema=schema, type_="foreignkey")
    op.create_foreign_key(
        new_name,
        table,
        ref_table,
        columns,
        ref_columns,
        source_schema=schema,
        referent_schema=ref_schema,
        ondelete=ondelete,
    )


def upgrade() -> None:
    # instrument 삭제 시 시세/지표 연쇄삭제 차단
    _swap_fk(
        table="price_daily",
        schema="market",
        old_name="fk_price_daily_instrument_id_instrument",
        new_name="fk_price_daily_instrument_restrict",
        columns=["instrument_id"],
        ref_schema="market",
        ref_table="instrument",
        ref_columns=["instrument_id"],
        ondelete="RESTRICT",
    )
    # indicator_daily FK 이름은 마이그레이션마다 다를 수 있어 동적 조회
    bind = op.get_bind()
    row = bind.execute(
        __import__("sqlalchemy").text(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'market.indicator_daily'::regclass
              AND contype = 'f'
              AND pg_get_constraintdef(oid) ILIKE '%instrument_id%'
            LIMIT 1
            """
        )
    ).scalar()
    if row:
        _swap_fk(
            table="indicator_daily",
            schema="market",
            old_name=str(row),
            new_name="fk_indicator_daily_instrument_restrict",
            columns=["instrument_id"],
            ref_schema="market",
            ref_table="instrument",
            ref_columns=["instrument_id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    _swap_fk(
        table="price_daily",
        schema="market",
        old_name="fk_price_daily_instrument_restrict",
        new_name="fk_price_daily_instrument_id_instrument",
        columns=["instrument_id"],
        ref_schema="market",
        ref_table="instrument",
        ref_columns=["instrument_id"],
        ondelete="CASCADE",
    )
    bind = op.get_bind()
    row = bind.execute(
        __import__("sqlalchemy").text(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'market.indicator_daily'::regclass
              AND contype = 'f'
              AND pg_get_constraintdef(oid) ILIKE '%instrument_id%'
            LIMIT 1
            """
        )
    ).scalar()
    if row:
        _swap_fk(
            table="indicator_daily",
            schema="market",
            old_name=str(row),
            new_name="fk_indicator_daily_instrument_id_instrument",
            columns=["instrument_id"],
            ref_schema="market",
            ref_table="instrument",
            ref_columns=["instrument_id"],
            ondelete="CASCADE",
        )
