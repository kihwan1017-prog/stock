"""STEP 8-9C-1 — JSONB roles → auth.user_role backfill

Revision ID: p5f6a7b8c9d0
Revises: o4e5f6a7b8c9
Create Date: 2026-07-27

Bootstrap admin 등이 user.roles(JSONB)만 갖고 user_role이 비어
Admin API가 403이 되는 드리프트를 치유한다.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "o4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JSONB roles 배열의 각 코드에 대해 user_role 누락분 INSERT
    # legacy alias: operator→admin, viewer/trader→user
    op.execute(
        sa.text(
            """
            WITH flattened AS (
              SELECT
                u.user_id,
                lower(trim(both '"' FROM elem::text)) AS raw_code
              FROM auth."user" u
              CROSS JOIN LATERAL jsonb_array_elements(
                COALESCE(u.roles, '[]'::jsonb)
              ) AS elem
            ),
            normalized AS (
              SELECT
                user_id,
                CASE raw_code
                  WHEN 'operator' THEN 'admin'
                  WHEN 'viewer' THEN 'user'
                  WHEN 'trader' THEN 'user'
                  ELSE raw_code
                END AS code
              FROM flattened
              WHERE raw_code IS NOT NULL AND raw_code <> ''
            ),
            mapped AS (
              SELECT DISTINCT n.user_id, r.role_id
              FROM normalized n
              INNER JOIN auth.role r ON r.code = n.code
              WHERE n.code IN ('admin', 'user')
            )
            INSERT INTO auth.user_role (user_id, role_id)
            SELECT m.user_id, m.role_id
            FROM mapped m
            WHERE NOT EXISTS (
              SELECT 1
              FROM auth.user_role ur
              WHERE ur.user_id = m.user_id
                AND ur.role_id = m.role_id
            )
            """
        )
    )


def downgrade() -> None:
    # 데이터 치유는 되돌리지 않음 (안전)
    pass
