"""STEP 12-13 — Portfolio Validation 보고서 저장

Revision ID: 55c454c73e69
Revises: 6464dedec667
Create Date: 2026-07-29

복수의 승인 Strategy Definition과 기존 Backtest 결과를 조합한 Portfolio
Validation(Correlation Matrix/Concentration/Risk Contribution/
Diversification Benefit/Duplicate Exposure/Robustness Score) 결과를
저장할 최소 신규 불변 테이블.

기존 backtest_run.parameters/strategy_performance_run.result_payload/
strategy_quality_gate_report/parameter_sensitivity_report/
monte_carlo_simulation_report는 전부 단일 Strategy(또는 단일 Run)
기준이라 다대다 Portfolio 조합을 담을 수 없어(§ 완료보고 Migration 항목
참고) 최소 컬럼의 새 테이블을 추가한다. strategy_definition_id/
backtest_run_id 각각에 FK를 두지 않고 JSONB 배열(다대다)로 저장한다
— 기존 두 테이블 모두 이미 RESTRICT/불변 정책이라 참조 무결성이 간접
보장된다. UPDATE API를 만들지 않는다(불변 — 재실행은 새 행).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "55c454c73e69"
down_revision: Union[str, Sequence[str], None] = "6464dedec667"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_validation_report",
        sa.Column("portfolio_validation_report_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("strategy_definition_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("backtest_run_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("weighting_method", sa.String(length=30), nullable=False),
        sa.Column("alignment_policy", sa.String(length=30), nullable=False),
        sa.Column("common_start_date", sa.Date(), nullable=False),
        sa.Column("common_end_date", sa.Date(), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("strategy_count", sa.Integer(), nullable=False),
        sa.Column("robustness_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("validation_status", sa.String(length=30), nullable=False),
        sa.Column("weights_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("common_period_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("portfolio_kpi_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correlation_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("concentration_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_contribution_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diversification_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duplicate_exposure_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("portfolio_equity_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("existing_validation_summary_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("robustness_breakdown_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status_reason_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        schema="trading",
    )
    op.create_index(
        "ix_portfolio_validation_report_input_hash",
        "portfolio_validation_report",
        ["report_input_hash"],
        unique=False,
        schema="trading",
    )
    op.create_index(
        "ux_portfolio_validation_report_idempotency_key",
        "portfolio_validation_report",
        ["idempotency_key"],
        unique=True,
        schema="trading",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_portfolio_validation_report_idempotency_key",
        table_name="portfolio_validation_report",
        schema="trading",
    )
    op.drop_index(
        "ix_portfolio_validation_report_input_hash",
        table_name="portfolio_validation_report",
        schema="trading",
    )
    op.drop_table("portfolio_validation_report", schema="trading")
