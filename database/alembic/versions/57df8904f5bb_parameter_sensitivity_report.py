"""STEP 12-11 — Parameter Sensitivity Analysis 보고서 저장

Revision ID: 57df8904f5bb
Revises: f5e26576a15b
Create Date: 2026-07-28

승인 Strategy Definition의 Parameter Sensitivity 분석(단일/최대 2개
파라미터 Variation, Robustness Score, Stable Range, Performance Cliff)
결과를 저장할 최소 신규 불변 테이블.

기존 backtest_run.parameters(Backtest Provenance 전용)/
strategy_performance_run.result_payload(P&L 지표 전용)/
strategy_quality_gate_report(Rule PASS/WARNING/FAIL 전용)는 모두 스키마
목적이 달라 이 STEP의 내용(Variation 목록 + Robustness Score + Stable
Range + Performance Cliff)을 자연스럽게 담을 수 없어(§ 완료보고 Migration
항목 참고) 최소 컬럼의 새 테이블을 추가한다. 각 Variation이 실행한
Backtest는 새 Backtest 구조를 만들지 않고 기존 backtest.backtest_run을
그대로 재사용(variation_results JSONB 내부에서 backtest_run_id로 참조).
UPDATE API를 만들지 않는다(불변 — 재평가는 새 행 INSERT).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "57df8904f5bb"
down_revision: Union[str, Sequence[str], None] = "f5e26576a15b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "parameter_sensitivity_report",
        sa.Column("parameter_sensitivity_report_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("strategy_id", sa.BigInteger(), nullable=False),
        sa.Column("base_backtest_run_id", sa.BigInteger(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("robustness_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("sensitivity_status", sa.String(length=30), nullable=False),
        sa.Column("successful_variation_count", sa.Integer(), nullable=False),
        sa.Column("failed_variation_count", sa.Integer(), nullable=False),
        sa.Column("parameter_specification", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("variation_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("variation_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sensitivity_analytics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stable_range", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("performance_cliffs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status_reason", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name="fk_parameter_sensitivity_report_strategy_definition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_backtest_run_id"],
            ["backtest.backtest_run.backtest_run_id"],
            name="fk_parameter_sensitivity_report_base_backtest_run",
            ondelete="RESTRICT",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_parameter_sensitivity_report_strategy_id",
        "parameter_sensitivity_report",
        ["strategy_id"],
        unique=False,
        schema="trading",
    )
    op.create_index(
        "ix_parameter_sensitivity_report_input_hash",
        "parameter_sensitivity_report",
        ["input_hash"],
        unique=False,
        schema="trading",
    )
    op.create_index(
        "ux_parameter_sensitivity_report_idempotency_key",
        "parameter_sensitivity_report",
        ["idempotency_key"],
        unique=True,
        schema="trading",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_parameter_sensitivity_report_idempotency_key",
        table_name="parameter_sensitivity_report",
        schema="trading",
    )
    op.drop_index(
        "ix_parameter_sensitivity_report_input_hash",
        table_name="parameter_sensitivity_report",
        schema="trading",
    )
    op.drop_index(
        "ix_parameter_sensitivity_report_strategy_id",
        table_name="parameter_sensitivity_report",
        schema="trading",
    )
    op.drop_table("parameter_sensitivity_report", schema="trading")
