"""create rbac role permission user_role role_permission

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-07-19 17:20:00.000000

STEP3: RBAC — role / permission / user_role / role_permission
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLES = [
    ("admin", "관리자", "전체 관리 권한"),
    ("operator", "운영자", "운영·거래 조작 권한"),
    ("viewer", "조회자", "조회 전용 권한"),
]

# code, name, category
PERMISSIONS = [
    # menus
    ("menu:dashboard", "메뉴:Dashboard", "menu"),
    ("menu:monitoring", "메뉴:모니터링", "menu"),
    ("menu:members", "메뉴:회원관리", "menu"),
    ("menu:roles", "메뉴:권한관리", "menu"),
    ("menu:accounts", "메뉴:계좌관리", "menu"),
    ("menu:trading", "메뉴:자동매매", "menu"),
    ("menu:orders", "메뉴:주문관리", "menu"),
    ("menu:trades", "메뉴:거래내역", "menu"),
    ("menu:portfolio", "메뉴:포트폴리오", "menu"),
    ("menu:strategies", "메뉴:전략관리", "menu"),
    ("menu:ai", "메뉴:AI관리", "menu"),
    ("menu:backtests", "메뉴:백테스트", "menu"),
    ("menu:news", "메뉴:뉴스", "menu"),
    ("menu:disclosures", "메뉴:공시", "menu"),
    ("menu:risk", "메뉴:Risk", "menu"),
    ("menu:scheduler", "메뉴:Scheduler", "menu"),
    ("menu:batch", "메뉴:배치", "menu"),
    ("menu:notifications", "메뉴:알림", "menu"),
    ("menu:kiwoom", "메뉴:키움", "menu"),
    ("menu:upbit", "메뉴:업비트", "menu"),
    ("menu:data", "메뉴:데이터", "menu"),
    ("menu:system_settings", "메뉴:시스템설정", "menu"),
    ("menu:env_settings", "메뉴:환경설정", "menu"),
    ("menu:logs", "메뉴:로그", "menu"),
    ("menu:db", "메뉴:DB관리", "menu"),
    ("menu:api", "메뉴:API관리", "menu"),
    ("menu:ollama", "메뉴:Ollama", "menu"),
    ("menu:docs", "메뉴:문서", "menu"),
    # APIs
    ("users:read", "회원 조회", "api"),
    ("users:write", "회원 등록/수정", "api"),
    ("users:delete", "회원 삭제", "api"),
    ("roles:read", "역할/권한 조회", "api"),
    ("roles:write", "역할/권한 변경", "api"),
    ("trading:read", "거래 조회", "api"),
    ("trading:write", "거래 조작", "api"),
    ("risk:write", "Risk 조작", "api"),
    ("ops:execute", "운영 실행", "api"),
    ("system:read", "시스템 조회", "api"),
    ("audit:read", "감사 로그 조회", "api"),
]

VIEWER_PERMS = {
    "menu:dashboard",
    "menu:monitoring",
    "menu:accounts",
    "menu:orders",
    "menu:trades",
    "menu:portfolio",
    "menu:strategies",
    "menu:ai",
    "menu:backtests",
    "menu:news",
    "menu:disclosures",
    "menu:risk",
    "menu:notifications",
    "menu:data",
    "menu:api",
    "menu:docs",
    "trading:read",
    "system:read",
}

OPERATOR_PERMS = VIEWER_PERMS | {
    "menu:trading",
    "menu:scheduler",
    "menu:batch",
    "menu:kiwoom",
    "menu:upbit",
    "menu:logs",
    "menu:env_settings",
    "trading:write",
    "risk:write",
    "ops:execute",
    "audit:read",
    "users:read",
}


def upgrade() -> None:
    op.create_table(
        "role",
        sa.Column(
            "role_id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "is_system",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("role_id", name=op.f("pk_role")),
        sa.UniqueConstraint("code", name="uq_role_code"),
        schema="auth",
    )

    op.create_table(
        "permission",
        sa.Column(
            "permission_id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "permission_id",
            name=op.f("pk_permission"),
        ),
        sa.UniqueConstraint("code", name="uq_permission_code"),
        schema="auth",
    )

    op.create_table(
        "user_role",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.user.user_id"],
            name=op.f("fk_user_role_user_id_user"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["auth.role.role_id"],
            name=op.f("fk_user_role_role_id_role"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id",
            "role_id",
            name=op.f("pk_user_role"),
        ),
        schema="auth",
    )

    op.create_table(
        "role_permission",
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["auth.role.role_id"],
            name=op.f("fk_role_permission_role_id_role"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["auth.permission.permission_id"],
            name=op.f(
                "fk_role_permission_permission_id_permission"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "role_id",
            "permission_id",
            name=op.f("pk_role_permission"),
        ),
        schema="auth",
    )

    role_table = sa.table(
        "role",
        sa.column("role_id", sa.BigInteger),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("is_system", sa.Boolean),
        schema="auth",
    )
    perm_table = sa.table(
        "permission",
        sa.column("permission_id", sa.BigInteger),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
        sa.column("description", sa.String),
        schema="auth",
    )
    role_perm_table = sa.table(
        "role_permission",
        sa.column("role_id", sa.BigInteger),
        sa.column("permission_id", sa.BigInteger),
        schema="auth",
    )
    user_role_table = sa.table(
        "user_role",
        sa.column("user_id", sa.BigInteger),
        sa.column("role_id", sa.BigInteger),
        schema="auth",
    )
    user_table = sa.table(
        "user",
        sa.column("user_id", sa.BigInteger),
        sa.column("roles", sa.JSON),
        schema="auth",
    )

    op.bulk_insert(
        role_table,
        [
            {
                "code": code,
                "name": name,
                "description": desc,
                "is_system": True,
            }
            for code, name, desc in ROLES
        ],
    )
    op.bulk_insert(
        perm_table,
        [
            {
                "code": code,
                "name": name,
                "category": category,
                "description": name,
            }
            for code, name, category in PERMISSIONS
        ],
    )

    bind = op.get_bind()
    role_rows = bind.execute(
        sa.text("SELECT role_id, code FROM auth.role")
    ).fetchall()
    perm_rows = bind.execute(
        sa.text("SELECT permission_id, code FROM auth.permission")
    ).fetchall()
    role_id_by_code = {row[1]: row[0] for row in role_rows}
    perm_id_by_code = {row[1]: row[0] for row in perm_rows}

    # admin: 전체
    admin_links = [
        {
            "role_id": role_id_by_code["admin"],
            "permission_id": pid,
        }
        for pid in perm_id_by_code.values()
    ]
    # operator / viewer
    operator_links = [
        {
            "role_id": role_id_by_code["operator"],
            "permission_id": perm_id_by_code[code],
        }
        for code in OPERATOR_PERMS
        if code in perm_id_by_code
    ]
    viewer_links = [
        {
            "role_id": role_id_by_code["viewer"],
            "permission_id": perm_id_by_code[code],
        }
        for code in VIEWER_PERMS
        if code in perm_id_by_code
    ]
    op.bulk_insert(
        role_perm_table,
        admin_links + operator_links + viewer_links,
    )

    # 기존 user.roles JSONB → user_role 마이그레이션
    users = bind.execute(
        sa.text("SELECT user_id, roles FROM auth.\"user\"")
    ).fetchall()
    user_role_rows = []
    for user_id, roles in users:
        codes: list[str] = []
        if isinstance(roles, list):
            codes = [str(item) for item in roles]
        elif isinstance(roles, str):
            codes = [roles]
        if not codes:
            codes = ["viewer"]
        for code in codes:
            mapped = code if code in role_id_by_code else "viewer"
            # legacy "user" → viewer
            if mapped == "user":
                mapped = "viewer"
            if mapped not in role_id_by_code:
                mapped = "viewer"
            user_role_rows.append(
                {
                    "user_id": user_id,
                    "role_id": role_id_by_code[mapped],
                }
            )
    # dedupe
    seen = set()
    unique_rows = []
    for row in user_role_rows:
        key = (row["user_id"], row["role_id"])
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    if unique_rows:
        op.bulk_insert(user_role_table, unique_rows)


def downgrade() -> None:
    op.drop_table("role_permission", schema="auth")
    op.drop_table("user_role", schema="auth")
    op.drop_table("permission", schema="auth")
    op.drop_table("role", schema="auth")
