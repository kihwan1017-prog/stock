"""viewer 역할에 trading:write 권한 부여 — 본인 계좌·Paper 주문 셀프서비스

Revision ID: n1b2c3d4e5f6
Revises: m9a0b1c2d3e4
Create Date: 2026-07-22

일반 회원가입(viewer)만으로는 trading:write가 없어 본인 Paper 계좌 생성·
주문 제출·취소 등 쓰기 작업이 전부 403이 나던 문제를 해결한다.
operator 전용 메뉴/권한(menu:trading, ops:execute, risk:write 등)은
변경하지 않는다 — viewer는 여전히 회원관리·시스템 리스크·스케줄러 등에는
접근할 수 없다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "m9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE_CODE = "viewer"
PERMISSION_CODE = "trading:write"


def upgrade() -> None:
    bind = op.get_bind()
    role_id = bind.execute(
        sa.text("SELECT role_id FROM auth.role WHERE code = :code"),
        {"code": ROLE_CODE},
    ).scalar()
    permission_id = bind.execute(
        sa.text(
            "SELECT permission_id FROM auth.permission WHERE code = :code"
        ),
        {"code": PERMISSION_CODE},
    ).scalar()
    if role_id is None or permission_id is None:
        return

    exists = bind.execute(
        sa.text(
            """
            SELECT 1 FROM auth.role_permission
            WHERE role_id = :role_id AND permission_id = :permission_id
            """
        ),
        {"role_id": role_id, "permission_id": permission_id},
    ).scalar()
    if exists:
        return

    bind.execute(
        sa.text(
            """
            INSERT INTO auth.role_permission (role_id, permission_id)
            VALUES (:role_id, :permission_id)
            """
        ),
        {"role_id": role_id, "permission_id": permission_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    role_id = bind.execute(
        sa.text("SELECT role_id FROM auth.role WHERE code = :code"),
        {"code": ROLE_CODE},
    ).scalar()
    permission_id = bind.execute(
        sa.text(
            "SELECT permission_id FROM auth.permission WHERE code = :code"
        ),
        {"code": PERMISSION_CODE},
    ).scalar()
    if role_id is None or permission_id is None:
        return

    bind.execute(
        sa.text(
            """
            DELETE FROM auth.role_permission
            WHERE role_id = :role_id AND permission_id = :permission_id
            """
        ),
        {"role_id": role_id, "permission_id": permission_id},
    )
