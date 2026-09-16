"""STEP 12-1A — Strategy Request 승인 재검증 스냅샷 + History FK 정책 보강

Revision ID: 27d47b2bb048
Revises: bfc6ab7d28b2
Create Date: 2026-07-28

STEP12-1 완료 후 발견된 두 가지 결함을 보완한다.

1. 승인 시점 스냅샷 부재: 기존 candidate_lifecycle_status_snapshot은
   "요청 생성 시점" 값만 보존해, 승인 시점에 Candidate 상태/Provenance가
   어땠는지 별도로 남길 컬럼이 없었다. STEP12-2에서 APPROVED Request를
   입력으로 쓸 때 요청 시점과 승인 시점 근거를 구분 추적할 수 있도록
   candidate_status_at_review / candidate_fingerprint_at_review 2개
   컬럼을 nullable로 추가한다(과거 행은 NULL 허용, 신규 approve()부터
   채워짐).
2. strategy_request_history FK가 ON DELETE CASCADE였던 점: strategy_request
   테이블은 Hard Delete가 금지된 설계(상태 전이만 허용)이지만, FK 정책
   자체가 CASCADE로 남아있으면 감사 이력 보존 원칙과 상충한다(요청 행이
   실수로/우회 경로로 삭제될 경우 이력까지 함께 사라짐). ON DELETE RESTRICT로
   변경해 History가 존재하는 Strategy Request는 DB 레벨에서 Hard Delete가
   차단되도록 한다.

기존 bfc6ab7d28b2 Migration 파일은 수정하지 않는다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "27d47b2bb048"
down_revision: Union[str, Sequence[str], None] = "bfc6ab7d28b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "strategy_request",
        sa.Column("candidate_status_at_review", sa.String(length=40), nullable=True),
        schema="ai",
    )
    op.add_column(
        "strategy_request",
        sa.Column(
            "candidate_fingerprint_at_review", sa.String(length=64), nullable=True
        ),
        schema="ai",
    )

    op.drop_constraint(
        "fk_ai_strategy_request_hist_request",
        "strategy_request_history",
        schema="ai",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_ai_strategy_request_hist_request",
        "strategy_request_history",
        "strategy_request",
        ["strategy_request_id"],
        ["strategy_request_id"],
        source_schema="ai",
        referent_schema="ai",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ai_strategy_request_hist_request",
        "strategy_request_history",
        schema="ai",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_ai_strategy_request_hist_request",
        "strategy_request_history",
        "strategy_request",
        ["strategy_request_id"],
        ["strategy_request_id"],
        source_schema="ai",
        referent_schema="ai",
        ondelete="CASCADE",
    )

    op.drop_column("strategy_request", "candidate_fingerprint_at_review", schema="ai")
    op.drop_column("strategy_request", "candidate_status_at_review", schema="ai")
