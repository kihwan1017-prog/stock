"""STEP 12-10 — Strategy Quality Gate 평가 결과 저장

Revision ID: f5e26576a15b
Revises: 417184ea4527
Create Date: 2026-07-28

승인 Strategy Definition의 자동 품질 심사(Rule 기반 PASS/WARNING/FAIL +
Recommendation + Risk Grade) 결과를 저장할 최소 신규 테이블.

기존 backtest_run.parameters/strategy_performance_run.result_payload는
각각 Backtest Provenance/성과 지표 전용 스키마라 이 STEP의 내용(Rule
목록 + Recommendation + Risk Grade + 산정 근거)을 자연스럽게 담을 수
없어(§ 완료보고 Migration 항목 참고) 최소 컬럼의 새 테이블을 추가한다.
평가 대상 Backtest Run/Walk-Forward Run은 FK로만 가리키고, 새 Backtest/
Walk-Forward 구조는 만들지 않는다(기존 결과를 조회만 한다).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f5e26576a15b"
down_revision: Union[str, Sequence[str], None] = "417184ea4527"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_quality_gate_report",
        sa.Column("quality_gate_report_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("strategy_id", sa.BigInteger(), nullable=False),
        sa.Column("backtest_run_id", sa.BigInteger(), nullable=True),
        sa.Column("walk_forward_run_id", sa.BigInteger(), nullable=True),
        sa.Column("recommendation", sa.String(length=30), nullable=False),
        sa.Column("risk_grade", sa.String(length=20), nullable=False),
        sa.Column("rules_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("threshold_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_grade_reason", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name="fk_quality_gate_report_strategy_definition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["backtest_run_id"],
            ["backtest.backtest_run.backtest_run_id"],
            name="fk_quality_gate_report_backtest_run",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["walk_forward_run_id"],
            ["trading.strategy_performance_run.strategy_performance_run_id"],
            name="fk_quality_gate_report_walk_forward_run",
            ondelete="SET NULL",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_strategy_quality_gate_report_strategy_id",
        "strategy_quality_gate_report",
        ["strategy_id"],
        unique=False,
        schema="trading",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_strategy_quality_gate_report_strategy_id",
        table_name="strategy_quality_gate_report",
        schema="trading",
    )
    op.drop_table("strategy_quality_gate_report", schema="trading")
