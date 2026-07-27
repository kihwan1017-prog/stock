"""RBAC Role을 admin / user 두 개로 정리

Revision ID: o2c3d4e5f6a7
Revises: n1b2c3d4e5f6
Create Date: 2026-07-22

정책:
- 허용 Role: admin, user
- viewer → user (코드 rename + JSONB 갱신)
- operator → admin (user_role 재매핑 후 operator Role 삭제)
- 레거시 JWT/입력 alias는 애플리케이션 레이어에서 처리
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "n1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    admin_id = bind.execute(
        sa.text("SELECT role_id FROM auth.role WHERE code = 'admin'")
    ).scalar()
    operator_id = bind.execute(
        sa.text("SELECT role_id FROM auth.role WHERE code = 'operator'")
    ).scalar()
    viewer_id = bind.execute(
        sa.text("SELECT role_id FROM auth.role WHERE code = 'viewer'")
    ).scalar()
    user_id = bind.execute(
        sa.text("SELECT role_id FROM auth.role WHERE code = 'user'")
    ).scalar()

    # 1) viewer → user (이미 user가 있으면 viewer 사용자만 이전)
    if viewer_id is not None and user_id is None:
        bind.execute(
            sa.text(
                """
                UPDATE auth.role
                SET code = 'user',
                    name = '일반 사용자',
                    description = '본인 계좌·주문·잔고·전략 관리'
                WHERE role_id = :role_id
                """
            ),
            {"role_id": viewer_id},
        )
        user_id = viewer_id
        viewer_id = None
    elif viewer_id is not None and user_id is not None:
        bind.execute(
            sa.text(
                """
                INSERT INTO auth.user_role (user_id, role_id)
                SELECT ur.user_id, :user_role_id
                FROM auth.user_role ur
                WHERE ur.role_id = :viewer_role_id
                  AND NOT EXISTS (
                    SELECT 1 FROM auth.user_role x
                    WHERE x.user_id = ur.user_id AND x.role_id = :user_role_id
                  )
                """
            ),
            {"user_role_id": user_id, "viewer_role_id": viewer_id},
        )
        bind.execute(
            sa.text("DELETE FROM auth.user_role WHERE role_id = :role_id"),
            {"role_id": viewer_id},
        )
        bind.execute(
            sa.text(
                "DELETE FROM auth.role_permission WHERE role_id = :role_id"
            ),
            {"role_id": viewer_id},
        )
        bind.execute(
            sa.text("DELETE FROM auth.role WHERE role_id = :role_id"),
            {"role_id": viewer_id},
        )

    # 2) operator 사용자를 admin으로 승격 후 operator 제거
    if operator_id is not None and admin_id is not None:
        bind.execute(
            sa.text(
                """
                INSERT INTO auth.user_role (user_id, role_id)
                SELECT ur.user_id, :admin_role_id
                FROM auth.user_role ur
                WHERE ur.role_id = :operator_role_id
                  AND NOT EXISTS (
                    SELECT 1 FROM auth.user_role x
                    WHERE x.user_id = ur.user_id AND x.role_id = :admin_role_id
                  )
                """
            ),
            {
                "admin_role_id": admin_id,
                "operator_role_id": operator_id,
            },
        )
        bind.execute(
            sa.text("DELETE FROM auth.user_role WHERE role_id = :role_id"),
            {"role_id": operator_id},
        )
        bind.execute(
            sa.text(
                "DELETE FROM auth.role_permission WHERE role_id = :role_id"
            ),
            {"role_id": operator_id},
        )
        bind.execute(
            sa.text("DELETE FROM auth.role WHERE role_id = :role_id"),
            {"role_id": operator_id},
        )

    # 3) auth.user.roles JSONB 정규화
    bind.execute(
        sa.text(
            """
            UPDATE auth."user"
            SET roles = (
              SELECT COALESCE(
                jsonb_agg(to_jsonb(mapped.role_code)),
                '[]'::jsonb
              )
              FROM (
                SELECT DISTINCT CASE lower(elem)
                  WHEN 'viewer' THEN 'user'
                  WHEN 'operator' THEN 'admin'
                  WHEN 'trader' THEN 'user'
                  ELSE lower(elem)
                END AS role_code
                FROM jsonb_array_elements_text(
                  CASE
                    WHEN jsonb_typeof(roles) = 'array' THEN roles
                    ELSE '[]'::jsonb
                  END
                ) AS elem
              ) AS mapped
            )
            """
        )
    )

    # 4) 신규 사용자 기본 Role
    bind.execute(
        sa.text(
            """
            ALTER TABLE auth."user"
            ALTER COLUMN roles SET DEFAULT '["user"]'::jsonb
            """
        )
    )


def downgrade() -> None:
    """admin/user → admin/operator/viewer 복원 (권한 매핑은 근사치)."""

    bind = op.get_bind()

    user_id = bind.execute(
        sa.text("SELECT role_id FROM auth.role WHERE code = 'user'")
    ).scalar()
    viewer_id = bind.execute(
        sa.text("SELECT role_id FROM auth.role WHERE code = 'viewer'")
    ).scalar()
    operator_id = bind.execute(
        sa.text("SELECT role_id FROM auth.role WHERE code = 'operator'")
    ).scalar()

    if user_id is not None and viewer_id is None:
        bind.execute(
            sa.text(
                """
                UPDATE auth.role
                SET code = 'viewer',
                    name = '조회자',
                    description = '조회 및 본인 거래'
                WHERE role_id = :role_id
                """
            ),
            {"role_id": user_id},
        )

    if operator_id is None:
        bind.execute(
            sa.text(
                """
                INSERT INTO auth.role (code, name, description, is_system)
                VALUES (
                  'operator',
                  '운영자',
                  '운영 실행 (downgrade 복원)',
                  true
                )
                """
            )
        )

    bind.execute(
        sa.text(
            """
            UPDATE auth."user"
            SET roles = (
              SELECT COALESCE(
                jsonb_agg(to_jsonb(mapped.role_code)),
                '[]'::jsonb
              )
              FROM (
                SELECT DISTINCT CASE lower(elem)
                  WHEN 'user' THEN 'viewer'
                  ELSE lower(elem)
                END AS role_code
                FROM jsonb_array_elements_text(
                  CASE
                    WHEN jsonb_typeof(roles) = 'array' THEN roles
                    ELSE '[]'::jsonb
                  END
                ) AS elem
              ) AS mapped
            )
            """
        )
    )

    bind.execute(
        sa.text(
            """
            ALTER TABLE auth."user"
            ALTER COLUMN roles SET DEFAULT '["viewer"]'::jsonb
            """
        )
    )
