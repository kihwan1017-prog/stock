"""Upbit market context research tables (CLEAN/LLM research only).

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6

REAL 주문/정책과 무관. DataLab scrape 없음.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v2w3x4y5z6a7"
down_revision: Union[str, Sequence[str], None] = "u1v2w3x4y5z6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_market_context_snapshot",
        sa.Column("snapshot_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("feature_key", sa.String(64), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stale_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality", sa.String(32), nullable=False),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="operation",
    )
    op.create_index(
        "ix_upbit_mkt_ctx_observed",
        "upbit_market_context_snapshot",
        ["observed_at"],
        schema="operation",
    )
    op.create_index(
        "ix_upbit_mkt_ctx_source_ts",
        "upbit_market_context_snapshot",
        ["source", "source_timestamp"],
        schema="operation",
    )

    op.create_table(
        "upbit_asset_context_snapshot",
        sa.Column("snapshot_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("feature_key", sa.String(64), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stale_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality", sa.String(32), nullable=False),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="operation",
    )
    op.create_index(
        "ix_upbit_asset_ctx_symbol_ts",
        "upbit_asset_context_snapshot",
        ["symbol", "source_timestamp"],
        schema="operation",
    )
    op.create_index(
        "ix_upbit_asset_ctx_feature",
        "upbit_asset_context_snapshot",
        ["feature_key", "observed_at"],
        schema="operation",
    )

    op.create_table(
        "upbit_asset_description_cache",
        sa.Column("cache_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("quality", sa.String(32), nullable=False),
        sa.Column("project_summary", sa.Text(), nullable=True),
        sa.Column("sector", sa.String(80), nullable=True),
        sa.Column("main_use_case", sa.Text(), nullable=True),
        sa.Column("token_characteristics", sa.Text(), nullable=True),
        sa.Column("known_risks", sa.Text(), nullable=True),
        sa.Column("official_links", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("stale_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="operation",
    )
    op.create_index(
        "ix_upbit_asset_desc_symbol",
        "upbit_asset_description_cache",
        ["symbol"],
        unique=True,
        schema="operation",
    )

    op.create_table(
        "upbit_llm_context_analysis",
        sa.Column("analysis_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("shadow_id", sa.BigInteger(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("context_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recommendation", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("entry_quality_score", sa.Integer(), nullable=True),
        sa.Column("quality", sa.String(32), nullable=False),
        sa.Column(
            "lookahead_ok",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="operation",
    )
    op.create_index(
        "ix_upbit_llm_ctx_symbol_asof",
        "upbit_llm_context_analysis",
        ["symbol", "context_as_of"],
        schema="operation",
    )
    op.create_index(
        "ix_upbit_llm_ctx_shadow",
        "upbit_llm_context_analysis",
        ["shadow_id"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_table("upbit_llm_context_analysis", schema="operation")
    op.drop_table("upbit_asset_description_cache", schema="operation")
    op.drop_table("upbit_asset_context_snapshot", schema="operation")
    op.drop_table("upbit_market_context_snapshot", schema="operation")
