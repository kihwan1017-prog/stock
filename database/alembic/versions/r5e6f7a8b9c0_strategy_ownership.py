"""전략 소유권 (STEP 8-3)

Revision ID: r5e6f7a8b9c0
Revises: q4e5f6a7b8c9
Create Date: 2026-07-23

- trading.strategy_definition: 소유권 루트 (SYSTEM/USER + visibility)
- trading.account_strategy_link: 계좌↔전략 연결
- strategy_deployment / strategy_performance_run 에 strategy_id·소유 메타 추가
- 승인 메타 decided_by='operator' 는 변경하지 않음
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "r5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "q4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_definition",
        sa.Column(
            "strategy_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("strategy_code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "market_type",
            sa.String(20),
            nullable=False,
            server_default="STOCK",
        ),
        sa.Column(
            "owner_type",
            sa.String(20),
            nullable=False,
            server_default="SYSTEM",
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "visibility",
            sa.String(20),
            nullable=False,
            server_default="PRIVATE",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "parameter_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("updated_by", sa.String(100), nullable=True),
        # 승인 메타 — RBAC Role 아님. 'operator' 문자열 보존 가능
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column(
            "approved_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("published_by", sa.String(100), nullable=True),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("source_strategy_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "deleted_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.user.user_id"],
            name="fk_strategy_definition_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_strategy_id"],
            ["trading.strategy_definition.strategy_id"],
            name="fk_strategy_definition_source",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "owner_type IN ('SYSTEM', 'USER')",
            name="ck_strategy_definition_owner_type",
        ),
        sa.CheckConstraint(
            "visibility IN ('PRIVATE', 'PUBLIC')",
            name="ck_strategy_definition_visibility",
        ),
        sa.CheckConstraint(
            "market_type IN ('STOCK', 'CRYPTO', 'ALL')",
            name="ck_strategy_definition_market_type",
        ),
        sa.CheckConstraint(
            "(owner_type = 'SYSTEM' AND user_id IS NULL) OR "
            "(owner_type = 'USER' AND user_id IS NOT NULL)",
            name="ck_strategy_definition_owner_user",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_strategy_definition_user_id",
        "strategy_definition",
        ["user_id"],
        schema="trading",
    )
    op.create_index(
        "ix_strategy_definition_visibility",
        "strategy_definition",
        ["visibility", "is_active"],
        schema="trading",
    )
    # SYSTEM: strategy_code 유일 (삭제되지 않은 행)
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_strategy_definition_system_code
            ON trading.strategy_definition (strategy_code)
            WHERE owner_type = 'SYSTEM' AND deleted_at IS NULL
            """
        )
    )
    # USER: (user_id, strategy_code) 유일
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_strategy_definition_user_code
            ON trading.strategy_definition (user_id, strategy_code)
            WHERE owner_type = 'USER' AND deleted_at IS NULL
            """
        )
    )

    op.create_table(
        "account_strategy_link",
        sa.Column(
            "account_strategy_link_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("strategy_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("paper_account_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "user_broker_account_id", sa.BigInteger(), nullable=True
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["trading.strategy_definition.strategy_id"],
            name="fk_account_strategy_link_strategy",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.user.user_id"],
            name="fk_account_strategy_link_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_account_id"],
            ["trading.paper_account.account_id"],
            name="fk_account_strategy_link_paper",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_broker_account_id"],
            ["trading.user_broker_account.user_broker_account_id"],
            name="fk_account_strategy_link_uba",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(paper_account_id IS NOT NULL AND "
            "user_broker_account_id IS NULL) OR "
            "(paper_account_id IS NULL AND "
            "user_broker_account_id IS NOT NULL)",
            name="ck_account_strategy_link_one_account",
        ),
        schema="trading",
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_account_strategy_link_paper
            ON trading.account_strategy_link (strategy_id, paper_account_id)
            WHERE paper_account_id IS NOT NULL AND is_active = true
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_account_strategy_link_uba
            ON trading.account_strategy_link (
                strategy_id, user_broker_account_id
            )
            WHERE user_broker_account_id IS NOT NULL AND is_active = true
            """
        )
    )

    # deployment 소유 컬럼
    op.add_column(
        "strategy_deployment",
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "strategy_deployment",
        sa.Column(
            "owner_type",
            sa.String(20),
            nullable=False,
            server_default="SYSTEM",
        ),
        schema="trading",
    )
    op.add_column(
        "strategy_deployment",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "strategy_deployment",
        sa.Column(
            "visibility",
            sa.String(20),
            nullable=False,
            server_default="PUBLIC",
        ),
        schema="trading",
    )
    op.create_foreign_key(
        "fk_strategy_deployment_definition",
        "strategy_deployment",
        "strategy_definition",
        ["strategy_id"],
        ["strategy_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_strategy_deployment_user",
        "strategy_deployment",
        "user",
        ["user_id"],
        ["user_id"],
        source_schema="trading",
        referent_schema="auth",
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_strategy_deployment_user_status",
        "strategy_deployment",
        ["user_id", "status_code"],
        schema="trading",
    )

    # 기존 전역 ACTIVE unique → partial (SYSTEM ACTIVE + USER ACTIVE 분리)
    op.drop_constraint(
        "uq_strategy_deployment_active_scope",
        "strategy_deployment",
        schema="trading",
        type_="unique",
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_strategy_deployment_system_active
            ON trading.strategy_deployment (
                market_code, symbol, mode_code, status_code
            )
            WHERE owner_type = 'SYSTEM' AND status_code = 'ACTIVE'
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_strategy_deployment_user_active
            ON trading.strategy_deployment (
                user_id, market_code, symbol, mode_code, status_code
            )
            WHERE owner_type = 'USER'
              AND user_id IS NOT NULL
              AND status_code = 'ACTIVE'
            """
        )
    )

    # performance run
    op.add_column(
        "strategy_performance_run",
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "strategy_performance_run",
        sa.Column(
            "requested_by_user_id", sa.BigInteger(), nullable=True
        ),
        schema="trading",
    )
    op.create_foreign_key(
        "fk_strategy_performance_run_definition",
        "strategy_performance_run",
        "strategy_definition",
        ["strategy_id"],
        ["strategy_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_strategy_performance_run_user",
        "strategy_performance_run",
        "user",
        ["requested_by_user_id"],
        ["user_id"],
        source_schema="trading",
        referent_schema="auth",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_strategy_performance_run_requested_by",
        "strategy_performance_run",
        ["requested_by_user_id"],
        schema="trading",
    )

    bind = op.get_bind()

    # Backfill: 기존 strategy_code → SYSTEM PUBLIC 정의 (임의 USER 배정 금지)
    bind.execute(
        sa.text(
            """
            INSERT INTO trading.strategy_definition (
                strategy_code,
                name,
                description,
                market_type,
                owner_type,
                user_id,
                visibility,
                is_active,
                parameter_payload,
                created_by,
                updated_by
            )
            SELECT
                x.strategy_code,
                x.strategy_code,
                'Backfilled platform strategy (STEP8-3)',
                x.market_type,
                'SYSTEM',
                NULL,
                'PUBLIC',
                true,
                '{}'::jsonb,
                'MIGRATION_STEP8_3',
                'MIGRATION_STEP8_3'
            FROM (
                SELECT DISTINCT ON (strategy_code)
                    strategy_code,
                    CASE
                        WHEN upper(market_code) IN (
                            'UPBIT', 'CRYPTO', 'KRW', 'BTC'
                        ) THEN 'CRYPTO'
                        ELSE 'STOCK'
                    END AS market_type
                FROM (
                    SELECT strategy_code, market_code
                    FROM trading.strategy_deployment
                    UNION ALL
                    SELECT strategy_code, market_code
                    FROM trading.strategy_performance_run
                ) AS src
                WHERE strategy_code IS NOT NULL
                  AND btrim(strategy_code) <> ''
                ORDER BY strategy_code, market_code
            ) AS x
            WHERE NOT EXISTS (
                SELECT 1
                FROM trading.strategy_definition s
                WHERE s.strategy_code = x.strategy_code
                  AND s.owner_type = 'SYSTEM'
                  AND s.deleted_at IS NULL
            )
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE trading.strategy_deployment d
            SET
                strategy_id = s.strategy_id,
                owner_type = 'SYSTEM',
                user_id = NULL,
                visibility = 'PUBLIC'
            FROM trading.strategy_definition s
            WHERE s.strategy_code = d.strategy_code
              AND s.owner_type = 'SYSTEM'
              AND s.deleted_at IS NULL
              AND d.strategy_id IS NULL
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE trading.strategy_performance_run r
            SET strategy_id = s.strategy_id
            FROM trading.strategy_definition s
            WHERE s.strategy_code = r.strategy_code
              AND s.owner_type = 'SYSTEM'
              AND s.deleted_at IS NULL
              AND r.strategy_id IS NULL
            """
        )
    )

    # 승인 메타 보존 검증용 카운트 (변경하지 않음)
    operator_cnt = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)::int
            FROM trading.strategy_approval_run
            WHERE decided_by = 'operator'
               OR requested_by = 'operator'
            """
        )
    ).scalar() or 0

    total_def = bind.execute(
        sa.text(
            "SELECT COUNT(*)::int FROM trading.strategy_definition"
        )
    ).scalar() or 0
    system_cnt = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)::int FROM trading.strategy_definition
            WHERE owner_type='SYSTEM'
            """
        )
    ).scalar() or 0
    public_cnt = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)::int FROM trading.strategy_definition
            WHERE visibility='PUBLIC' AND deleted_at IS NULL
            """
        )
    ).scalar() or 0

    print(
        "STEP8-3 backfill: "
        f"definitions={total_def}, system={system_cnt}, "
        f"public={public_cnt}, operator_meta_preserved={operator_cnt}"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_strategy_performance_run_requested_by",
        table_name="strategy_performance_run",
        schema="trading",
    )
    op.drop_constraint(
        "fk_strategy_performance_run_user",
        "strategy_performance_run",
        schema="trading",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_strategy_performance_run_definition",
        "strategy_performance_run",
        schema="trading",
        type_="foreignkey",
    )
    op.drop_column(
        "strategy_performance_run",
        "requested_by_user_id",
        schema="trading",
    )
    op.drop_column(
        "strategy_performance_run",
        "strategy_id",
        schema="trading",
    )

    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS trading.uq_strategy_deployment_user_active"
        )
    )
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS trading.uq_strategy_deployment_system_active"
        )
    )
    op.drop_index(
        "ix_strategy_deployment_user_status",
        table_name="strategy_deployment",
        schema="trading",
    )
    op.drop_constraint(
        "fk_strategy_deployment_user",
        "strategy_deployment",
        schema="trading",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_strategy_deployment_definition",
        "strategy_deployment",
        schema="trading",
        type_="foreignkey",
    )
    op.drop_column(
        "strategy_deployment", "visibility", schema="trading"
    )
    op.drop_column(
        "strategy_deployment", "user_id", schema="trading"
    )
    op.drop_column(
        "strategy_deployment", "owner_type", schema="trading"
    )
    op.drop_column(
        "strategy_deployment", "strategy_id", schema="trading"
    )
    op.create_unique_constraint(
        "uq_strategy_deployment_active_scope",
        "strategy_deployment",
        ["market_code", "symbol", "mode_code", "status_code"],
        schema="trading",
    )

    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS trading.uq_account_strategy_link_uba"
        )
    )
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS trading.uq_account_strategy_link_paper"
        )
    )
    op.drop_table("account_strategy_link", schema="trading")

    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS trading.uq_strategy_definition_user_code"
        )
    )
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS trading.uq_strategy_definition_system_code"
        )
    )
    op.drop_index(
        "ix_strategy_definition_visibility",
        table_name="strategy_definition",
        schema="trading",
    )
    op.drop_index(
        "ix_strategy_definition_user_id",
        table_name="strategy_definition",
        schema="trading",
    )
    op.drop_table("strategy_definition", schema="trading")
