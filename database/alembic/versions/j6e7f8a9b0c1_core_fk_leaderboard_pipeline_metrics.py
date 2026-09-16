"""P0 — leaderboard/pipeline/metric FK + instrument RESTRICT 확장

Revision ID: j6e7f8a9b0c1
Revises: i5d6e7f8a9b0
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = "i5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _swap_instrument_fk(
    *,
    table: str,
    old_name: str | None,
    new_name: str,
) -> None:
    """market.* → instrument CASCADE를 RESTRICT로 교체."""

    bind = op.get_bind()
    name = old_name
    if not name:
        name = bind.execute(
            sa.text(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = (:reg)::regclass
                  AND contype = 'f'
                  AND pg_get_constraintdef(oid) ILIKE '%instrument_id%'
                LIMIT 1
                """
            ),
            {"reg": f"market.{table}"},
        ).scalar()
    if not name:
        return
    op.drop_constraint(str(name), table, schema="market", type_="foreignkey")
    op.create_foreign_key(
        new_name,
        table,
        "instrument",
        ["instrument_id"],
        ["instrument_id"],
        source_schema="market",
        referent_schema="market",
        ondelete="RESTRICT",
    )


def _null_orphan_then_fk(
    *,
    schema: str,
    table: str,
    column: str,
    ref_schema: str,
    ref_table: str,
    ref_column: str,
    fk_name: str,
    ondelete: str,
    nullable: bool,
) -> None:
    """orphan 정리 후 FK 생성."""

    if nullable:
        op.execute(
            sa.text(
                f"""
                UPDATE {schema}.{table} AS child
                SET {column} = NULL
                WHERE {column} IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM {ref_schema}.{ref_table} AS parent
                    WHERE parent.{ref_column} = child.{column}
                  )
                """
            )
        )
    else:
        # NOT NULL 컬럼 — orphan 행 삭제 (참조 무결성 우선)
        op.execute(
            sa.text(
                f"""
                DELETE FROM {schema}.{table} AS child
                WHERE NOT EXISTS (
                    SELECT 1 FROM {ref_schema}.{ref_table} AS parent
                    WHERE parent.{ref_column} = child.{column}
                )
                """
            )
        )
    op.create_foreign_key(
        fk_name,
        table,
        ref_table,
        [column],
        [ref_column],
        source_schema=schema,
        referent_schema=ref_schema,
        ondelete=ondelete,
    )


def upgrade() -> None:
    # --- strategy_leaderboard_entry ---
    _null_orphan_then_fk(
        schema="trading",
        table="strategy_leaderboard_entry",
        column="strategy_leaderboard_snapshot_id",
        ref_schema="trading",
        ref_table="strategy_leaderboard_snapshot",
        ref_column="strategy_leaderboard_snapshot_id",
        fk_name="fk_leaderboard_entry_snapshot",
        ondelete="CASCADE",
        nullable=False,
    )
    _null_orphan_then_fk(
        schema="trading",
        table="strategy_leaderboard_entry",
        column="strategy_performance_run_id",
        ref_schema="trading",
        ref_table="strategy_performance_run",
        ref_column="strategy_performance_run_id",
        fk_name="fk_leaderboard_entry_performance_run",
        ondelete="RESTRICT",
        nullable=False,
    )

    # --- strategy_deployment_pipeline ---
    _null_orphan_then_fk(
        schema="trading",
        table="strategy_deployment_pipeline",
        column="strategy_selection_run_id",
        ref_schema="ai",
        ref_table="strategy_selection_run",
        ref_column="strategy_selection_run_id",
        fk_name="fk_deployment_pipeline_selection",
        ondelete="RESTRICT",
        nullable=False,
    )
    _null_orphan_then_fk(
        schema="trading",
        table="strategy_deployment_pipeline",
        column="strategy_approval_run_id",
        ref_schema="trading",
        ref_table="strategy_approval_run",
        ref_column="strategy_approval_run_id",
        fk_name="fk_deployment_pipeline_approval",
        ondelete="SET NULL",
        nullable=True,
    )
    _null_orphan_then_fk(
        schema="trading",
        table="strategy_deployment_pipeline",
        column="strategy_deployment_id",
        ref_schema="trading",
        ref_table="strategy_deployment",
        ref_column="strategy_deployment_id",
        fk_name="fk_deployment_pipeline_deployment",
        ondelete="SET NULL",
        nullable=True,
    )
    _null_orphan_then_fk(
        schema="trading",
        table="strategy_deployment_pipeline",
        column="strategy_runtime_switch_id",
        ref_schema="trading",
        ref_table="strategy_runtime_switch",
        ref_column="strategy_runtime_switch_id",
        fk_name="fk_deployment_pipeline_runtime_switch",
        ondelete="SET NULL",
        nullable=True,
    )

    # --- performance metric / walk-forward ---
    _null_orphan_then_fk(
        schema="trading",
        table="strategy_performance_metric",
        column="strategy_performance_run_id",
        ref_schema="trading",
        ref_table="strategy_performance_run",
        ref_column="strategy_performance_run_id",
        fk_name="fk_performance_metric_run",
        ondelete="CASCADE",
        nullable=False,
    )
    _null_orphan_then_fk(
        schema="trading",
        table="walk_forward_window_metric",
        column="strategy_performance_run_id",
        ref_schema="trading",
        ref_table="strategy_performance_run",
        ref_column="strategy_performance_run_id",
        fk_name="fk_walk_forward_metric_run",
        ondelete="CASCADE",
        nullable=False,
    )

    # --- AI selection → performance run ---
    _null_orphan_then_fk(
        schema="ai",
        table="strategy_selection_run",
        column="selected_performance_run_id",
        ref_schema="trading",
        ref_table="strategy_performance_run",
        ref_column="strategy_performance_run_id",
        fk_name="fk_selection_run_performance",
        ondelete="RESTRICT",
        nullable=False,
    )

    # --- instrument CASCADE → RESTRICT (틱/호가/분봉) ---
    for table, old_name, new_name in (
        (
            "candle_minute",
            "fk_candle_minute_instrument_id",
            "fk_candle_minute_instrument_restrict",
        ),
        (
            "trade_tick",
            None,
            "fk_trade_tick_instrument_restrict",
        ),
        (
            "quote_snapshot",
            None,
            "fk_quote_snapshot_instrument_restrict",
        ),
        (
            "orderbook_snapshot",
            None,
            "fk_orderbook_snapshot_instrument_restrict",
        ),
    ):
        _swap_instrument_fk(
            table=table,
            old_name=old_name,
            new_name=new_name,
        )


def downgrade() -> None:
    for fk, table, schema in (
        ("fk_selection_run_performance", "strategy_selection_run", "ai"),
        ("fk_walk_forward_metric_run", "walk_forward_window_metric", "trading"),
        ("fk_performance_metric_run", "strategy_performance_metric", "trading"),
        (
            "fk_deployment_pipeline_runtime_switch",
            "strategy_deployment_pipeline",
            "trading",
        ),
        (
            "fk_deployment_pipeline_deployment",
            "strategy_deployment_pipeline",
            "trading",
        ),
        (
            "fk_deployment_pipeline_approval",
            "strategy_deployment_pipeline",
            "trading",
        ),
        (
            "fk_deployment_pipeline_selection",
            "strategy_deployment_pipeline",
            "trading",
        ),
        (
            "fk_leaderboard_entry_performance_run",
            "strategy_leaderboard_entry",
            "trading",
        ),
        ("fk_leaderboard_entry_snapshot", "strategy_leaderboard_entry", "trading"),
    ):
        op.drop_constraint(fk, table, schema=schema, type_="foreignkey")

    # instrument FK는 CASCADE로 복구 (이름 동적)
    bind = op.get_bind()
    for table in (
        "candle_minute",
        "trade_tick",
        "quote_snapshot",
        "orderbook_snapshot",
    ):
        name = bind.execute(
            sa.text(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = (:reg)::regclass
                  AND contype = 'f'
                  AND pg_get_constraintdef(oid) ILIKE '%instrument_id%'
                LIMIT 1
                """
            ),
            {"reg": f"market.{table}"},
        ).scalar()
        if not name:
            continue
        op.drop_constraint(str(name), table, schema="market", type_="foreignkey")
        op.create_foreign_key(
            f"fk_{table}_instrument_id",
            table,
            "instrument",
            ["instrument_id"],
            ["instrument_id"],
            source_schema="market",
            referent_schema="market",
            ondelete="CASCADE",
        )
