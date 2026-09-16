"""STEP 12-12 — Monte Carlo Simulation 보고서 저장

Revision ID: 6464dedec667
Revises: 57df8904f5bb
Create Date: 2026-07-28

승인 Strategy Definition의 기존 Backtest Trade 결과를 확률적으로
재표본화(TRADE_ORDER_SHUFFLE/BOOTSTRAP_WITH_REPLACEMENT/BLOCK_BOOTSTRAP)한
Monte Carlo Simulation 결과를 저장할 최소 신규 불변 테이블.

기존 backtest_run.parameters/strategy_performance_run.result_payload/
strategy_quality_gate_report/parameter_sensitivity_report는 전부 스키마
목적이 달라 이 STEP의 내용(Percentile/Confidence Interval/대표
Simulation/Risk of Ruin/Robustness Score)을 자연스럽게 담을 수 없어(§
완료보고 Migration 항목 참고) 최소 컬럼의 새 테이블을 추가한다.
1000~10000개 개별 Simulation 원본은 저장하지 않는다(집계+대표만). 새
Backtest/Trade/Equity 구조는 만들지 않고 기존 backtest.backtest_run/
backtest_trade를 조회만 한다. UPDATE API를 만들지 않는다(불변).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6464dedec667"
down_revision: Union[str, Sequence[str], None] = "57df8904f5bb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monte_carlo_simulation_report",
        sa.Column("monte_carlo_report_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("strategy_id", sa.BigInteger(), nullable=False),
        sa.Column("backtest_run_id", sa.BigInteger(), nullable=False),
        sa.Column("simulation_method", sa.String(length=30), nullable=False),
        sa.Column("simulation_count", sa.Integer(), nullable=False),
        sa.Column("random_seed", sa.BigInteger(), nullable=False),
        sa.Column("confidence_level", sa.Numeric(4, 2), nullable=False),
        sa.Column("ruin_threshold_percent", sa.Numeric(6, 2), nullable=False),
        sa.Column("block_size", sa.Integer(), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("valid_simulation_count", sa.Integer(), nullable=False),
        sa.Column("failed_simulation_count", sa.Integer(), nullable=False),
        sa.Column("risk_of_ruin_percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("robustness_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("monte_carlo_status", sa.String(length=30), nullable=False),
        sa.Column("percentile_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence_interval_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("representative_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure_summary_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.Column("report_input_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("requested_by", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["trading.strategy_definition.strategy_id"],
            name="fk_monte_carlo_report_strategy_definition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["backtest_run_id"],
            ["backtest.backtest_run.backtest_run_id"],
            name="fk_monte_carlo_report_backtest_run",
            ondelete="RESTRICT",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_monte_carlo_report_strategy_id",
        "monte_carlo_simulation_report",
        ["strategy_id"],
        unique=False,
        schema="trading",
    )
    op.create_index(
        "ix_monte_carlo_report_input_hash",
        "monte_carlo_simulation_report",
        ["report_input_hash"],
        unique=False,
        schema="trading",
    )
    op.create_index(
        "ux_monte_carlo_report_idempotency_key",
        "monte_carlo_simulation_report",
        ["idempotency_key"],
        unique=True,
        schema="trading",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_monte_carlo_report_idempotency_key",
        table_name="monte_carlo_simulation_report",
        schema="trading",
    )
    op.drop_index(
        "ix_monte_carlo_report_input_hash",
        table_name="monte_carlo_simulation_report",
        schema="trading",
    )
    op.drop_index(
        "ix_monte_carlo_report_strategy_id",
        table_name="monte_carlo_simulation_report",
        schema="trading",
    )
    op.drop_table("monte_carlo_simulation_report", schema="trading")
