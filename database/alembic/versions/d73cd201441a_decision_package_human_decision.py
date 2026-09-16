"""STEP 12-15 — Decision Package & Human Decision 저장

Revision ID: d73cd201441a
Revises: 339f8d3de392
Create Date: 2026-07-29

이미 생성된 Strategy Definition/Approval Snapshot/Backtest/Performance/
Walk-Forward/Quality Gate/Parameter Sensitivity/Monte Carlo/Portfolio
Validation/Explainability 결과를 하나의 동결된 Decision Package로 묶고,
사람이 내린 불변 결정(Human Decision)을 별도로 기록한다. 기존 검증
Report 스키마 전부 "자기 자신의 검증 결과"만 담는 구조라 여러 Report를
가로지르는 승인 검토 묶음 + 결정을 담을 수 없어 최소 신규 불변 테이블
2개를 추가한다. Decision Package/Human Decision 모두 UPDATE API를
만들지 않는다(불변 — 재검토는 새 Package/새 Decision).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d73cd201441a"
down_revision: Union[str, Sequence[str], None] = "339f8d3de392"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_decision_package",
        sa.Column("package_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "strategy_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_definition.strategy_id",
                ondelete="RESTRICT",
                name="fk_decision_package_strategy_definition",
            ),
            nullable=False,
        ),
        sa.Column("explainability_report_id", sa.BigInteger(), nullable=False),
        sa.Column("quality_gate_report_id", sa.BigInteger(), nullable=True),
        sa.Column("parameter_sensitivity_report_id", sa.BigInteger(), nullable=True),
        sa.Column("monte_carlo_report_id", sa.BigInteger(), nullable=True),
        sa.Column("portfolio_validation_report_id", sa.BigInteger(), nullable=True),
        sa.Column("package_note", sa.Text(), nullable=True),
        sa.Column("package_status", sa.String(length=30), nullable=False),
        sa.Column("required_evidence_complete", sa.Boolean(), nullable=False),
        sa.Column("provenance_valid", sa.Boolean(), nullable=False),
        sa.Column("explainability_complete", sa.Boolean(), nullable=False),
        sa.Column("blocking_evidence_count", sa.Integer(), nullable=False),
        sa.Column("warning_evidence_count", sa.Integer(), nullable=False),
        sa.Column("missing_evidence_count", sa.Integer(), nullable=False),
        sa.Column("human_review_required", sa.Boolean(), nullable=False),
        sa.Column("readiness_reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("strategy_definition_version", sa.Integer(), nullable=True),
        sa.Column("definition_hash", sa.String(length=64), nullable=True),
        sa.Column("executable_hash", sa.String(length=64), nullable=True),
        sa.Column("approval_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("selected_report_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("selected_report_hashes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("explainability_input_hash", sa.String(length=64), nullable=True),
        sa.Column("evidence_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("checklist_template_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checklist_template_version", sa.String(length=20), nullable=False),
        sa.Column("package_algorithm_version", sa.String(length=20), nullable=False),
        sa.Column("package_input_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("requester_id", sa.BigInteger(), nullable=True),
        sa.Column("package_created_by", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        schema="trading",
    )
    op.create_index(
        "ix_decision_package_strategy_id", "strategy_decision_package", ["strategy_id"],
        unique=False, schema="trading",
    )
    op.create_index(
        "ix_decision_package_input_hash", "strategy_decision_package", ["package_input_hash"],
        unique=False, schema="trading",
    )
    op.create_index(
        "ux_decision_package_idempotency_key", "strategy_decision_package", ["idempotency_key"],
        unique=True, schema="trading", postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "strategy_human_decision",
        sa.Column("decision_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "package_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "trading.strategy_decision_package.package_id",
                ondelete="RESTRICT",
                name="fk_human_decision_package",
            ),
            nullable=False,
        ),
        sa.Column("strategy_id", sa.BigInteger(), nullable=False),
        sa.Column("decision_type", sa.String(length=30), nullable=False),
        sa.Column("reason_code", sa.String(length=50), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column("checklist_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("acknowledged_warnings_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("promotion_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("promotion_ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promotion_readiness_hash", sa.String(length=64), nullable=True),
        sa.Column("requester_id", sa.BigInteger(), nullable=True),
        sa.Column("package_created_by", sa.String(length=100), nullable=False),
        sa.Column("decided_by", sa.String(length=100), nullable=False),
        sa.Column("same_actor_warning", sa.Boolean(), nullable=False),
        sa.Column("decision_input_hash", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        schema="trading",
    )
    op.create_index(
        "ix_human_decision_strategy_id", "strategy_human_decision", ["strategy_id"],
        unique=False, schema="trading",
    )
    op.create_index(
        "ix_human_decision_input_hash", "strategy_human_decision", ["decision_input_hash"],
        unique=False, schema="trading",
    )
    op.create_index(
        "ux_human_decision_package_id", "strategy_human_decision", ["package_id"],
        unique=True, schema="trading",
    )
    op.create_index(
        "ux_human_decision_idempotency_key", "strategy_human_decision", ["idempotency_key"],
        unique=True, schema="trading", postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_human_decision_idempotency_key", table_name="strategy_human_decision", schema="trading")
    op.drop_index("ux_human_decision_package_id", table_name="strategy_human_decision", schema="trading")
    op.drop_index("ix_human_decision_input_hash", table_name="strategy_human_decision", schema="trading")
    op.drop_index("ix_human_decision_strategy_id", table_name="strategy_human_decision", schema="trading")
    op.drop_table("strategy_human_decision", schema="trading")

    op.drop_index("ux_decision_package_idempotency_key", table_name="strategy_decision_package", schema="trading")
    op.drop_index("ix_decision_package_input_hash", table_name="strategy_decision_package", schema="trading")
    op.drop_index("ix_decision_package_strategy_id", table_name="strategy_decision_package", schema="trading")
    op.drop_table("strategy_decision_package", schema="trading")
