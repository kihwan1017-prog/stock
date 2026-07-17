"""add dart corp and disclosure enrichment news failure

Revision ID: e6c2d93f5b12
Revises: d5b1c82e4a01
Create Date: 2026-07-18 08:45:00.000000

STEP37-02/03:
- disclosure.dart_corp
- dart_disclosure enrichment columns
- news.collection_failure
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e6c2d93f5b12"
down_revision: Union[str, Sequence[str], None] = "d5b1c82e4a01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dart_corp",
        sa.Column("corp_code", sa.String(length=8), nullable=False),
        sa.Column("corp_name", sa.String(length=200), nullable=False),
        sa.Column("stock_code", sa.String(length=20), nullable=True),
        sa.Column("modify_date", sa.Date(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "raw_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("corp_code", name="pk_dart_corp"),
        schema="disclosure",
    )
    op.create_index(
        "ix_dart_corp_stock_code",
        "dart_corp",
        ["stock_code"],
        unique=False,
        schema="disclosure",
    )

    op.add_column(
        "dart_disclosure",
        sa.Column(
            "category_code",
            sa.String(length=30),
            server_default=sa.text("'OTHER'"),
            nullable=False,
        ),
        schema="disclosure",
    )
    op.add_column(
        "dart_disclosure",
        sa.Column(
            "importance_score",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        schema="disclosure",
    )
    op.add_column(
        "dart_disclosure",
        sa.Column(
            "is_correction",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        schema="disclosure",
    )
    op.add_column(
        "dart_disclosure",
        sa.Column(
            "related_receipt_no",
            sa.String(length=20),
            nullable=True,
        ),
        schema="disclosure",
    )

    op.create_table(
        "collection_failure",
        sa.Column(
            "failure_id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("exchange_code", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("query_text", sa.String(length=300), nullable=True),
        sa.Column(
            "source_code",
            sa.String(length=30),
            server_default=sa.text("'NAVER'"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "extra_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "failure_id",
            name="pk_collection_failure",
        ),
        schema="news",
    )
    op.create_index(
        "ix_collection_failure_symbol_failed",
        "collection_failure",
        ["exchange_code", "symbol", "failed_at"],
        unique=False,
        schema="news",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_collection_failure_symbol_failed",
        table_name="collection_failure",
        schema="news",
    )
    op.drop_table("collection_failure", schema="news")
    op.drop_column(
        "dart_disclosure",
        "related_receipt_no",
        schema="disclosure",
    )
    op.drop_column(
        "dart_disclosure",
        "is_correction",
        schema="disclosure",
    )
    op.drop_column(
        "dart_disclosure",
        "importance_score",
        schema="disclosure",
    )
    op.drop_column(
        "dart_disclosure",
        "category_code",
        schema="disclosure",
    )
    op.drop_index(
        "ix_dart_corp_stock_code",
        table_name="dart_corp",
        schema="disclosure",
    )
    op.drop_table("dart_corp", schema="disclosure")
