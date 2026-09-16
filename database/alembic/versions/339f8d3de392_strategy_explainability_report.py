"""STEP 12-14 — Strategy Explainability & Decision Evidence 저장

Revision ID: 339f8d3de392
Revises: 55c454c73e69
Create Date: 2026-07-29

이미 완료된 검증 Report(Backtest/Performance/Walk-Forward/Quality Gate/
Parameter Sensitivity/Monte Carlo/Portfolio Validation)와 Strategy
Definition을 사람이 이해할 수 있게 재구성한 설명 + Evidence Reference +
Completeness/Decision Summary를 저장할 최소 신규 불변 테이블. 기존 검증
Report 스키마 전부 "자기 자신의 검증 결과"만 담는 구조라 여러 Report를
가로질러 참조하는 이 내용을 담을 수 없다(§ 완료보고 Migration 항목
참고). 참조하는 각 Report ID는 FK를 두지 않는다(선택적 조합, 어떤
Report도 owning table이 아님). UPDATE API를 만들지 않는다(불변 —
재실행은 새 행).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "339f8d3de392"
down_revision: Union[str, Sequence[str], None] = "55c454c73e69"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_explainability_report",
        sa.Column("explainability_report_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_definition.strategy_id",
                ondelete="RESTRICT",
                name="fk_explainability_report_strategy_definition",
            ),
            nullable=False,
        ),
        sa.Column("backtest_run_id", sa.BigInteger(), nullable=True),
        sa.Column("walk_forward_run_id", sa.BigInteger(), nullable=True),
        sa.Column("quality_gate_report_id", sa.BigInteger(), nullable=True),
        sa.Column("parameter_sensitivity_report_id", sa.BigInteger(), nullable=True),
        sa.Column("monte_carlo_report_id", sa.BigInteger(), nullable=True),
        sa.Column("portfolio_validation_report_id", sa.BigInteger(), nullable=True),
        sa.Column("explanation_mode", sa.String(length=40), nullable=False),
        sa.Column("explanation_language", sa.String(length=10), nullable=False),
        sa.Column("strategy_overview_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rule_explanation_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("backtest_evidence_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("walk_forward_evidence_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_gate_evidence_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sensitivity_evidence_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("monte_carlo_evidence_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("portfolio_evidence_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision_checklist_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_reference_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("missing_evidence_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision_summary_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("completeness_score", sa.Numeric(6, 2), nullable=False),
        sa.Column("completeness_status", sa.String(length=20), nullable=False),
        sa.Column("assisted_interpretation_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provenance_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("template_version", sa.String(length=20), nullable=False),
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
        "ix_explainability_report_strategy_id",
        "strategy_explainability_report",
        ["strategy_id"],
        unique=False,
        schema="trading",
    )
    op.create_index(
        "ix_explainability_report_input_hash",
        "strategy_explainability_report",
        ["report_input_hash"],
        unique=False,
        schema="trading",
    )
    op.create_index(
        "ux_explainability_report_idempotency_key",
        "strategy_explainability_report",
        ["idempotency_key"],
        unique=True,
        schema="trading",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_explainability_report_idempotency_key",
        table_name="strategy_explainability_report",
        schema="trading",
    )
    op.drop_index(
        "ix_explainability_report_input_hash",
        table_name="strategy_explainability_report",
        schema="trading",
    )
    op.drop_index(
        "ix_explainability_report_strategy_id",
        table_name="strategy_explainability_report",
        schema="trading",
    )
    op.drop_table("strategy_explainability_report", schema="trading")
