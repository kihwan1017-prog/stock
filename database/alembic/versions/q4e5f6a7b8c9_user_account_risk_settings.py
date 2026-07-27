"""회원·계좌·시스템 리스크 설정 테이블 (STEP 8-2)

Revision ID: q4e5f6a7b8c9
Revises: p3d4e5f6a7b8
Create Date: 2026-07-23

비율 단위: fraction (5% = 0.050000). 금액: NUMERIC.
Paper는 UserBrokerAccount에 연결하지 않음 — 사용자 기본 설정만 적용.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "p3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 시스템 기본 (singleton) ---
    op.create_table(
        "system_risk_setting",
        sa.Column(
            "system_risk_setting_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column(
            "singleton_key",
            sa.String(20),
            nullable=False,
            server_default="DEFAULT",
        ),
        sa.Column(
            "max_order_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default="100000",
        ),
        sa.Column(
            "daily_max_order_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default="1000000",
        ),
        sa.Column(
            "max_total_investment_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default="5000000",
        ),
        sa.Column(
            "max_position_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default="1000000",
        ),
        sa.Column(
            "max_position_count",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column(
            "max_position_weight",
            sa.Numeric(10, 6),
            nullable=False,
            server_default="0.200000",
        ),
        sa.Column(
            "allow_duplicate_buy",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "daily_max_loss_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default="300000",
        ),
        sa.Column(
            "daily_max_loss_rate",
            sa.Numeric(10, 6),
            nullable=False,
            server_default="0.050000",
        ),
        sa.Column(
            "stop_loss_rate",
            sa.Numeric(10, 6),
            nullable=False,
            server_default="0.050000",
        ),
        sa.Column(
            "take_profit_rate",
            sa.Numeric(10, 6),
            nullable=False,
            server_default="0.100000",
        ),
        sa.Column(
            "trailing_stop_rate",
            sa.Numeric(10, 6),
            nullable=True,
            server_default="0.030000",
        ),
        sa.Column(
            "auto_trading_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "buy_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "sell_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "sell_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "account_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("updated_by", sa.String(100), nullable=True),
        sa.UniqueConstraint(
            "singleton_key",
            name="uq_system_risk_setting_singleton",
        ),
        sa.CheckConstraint(
            "max_order_amount >= 0",
            name="ck_system_risk_max_order_amount",
        ),
        sa.CheckConstraint(
            "daily_max_order_amount >= 0",
            name="ck_system_risk_daily_max_order",
        ),
        sa.CheckConstraint(
            "max_total_investment_amount >= 0",
            name="ck_system_risk_max_total_invest",
        ),
        sa.CheckConstraint(
            "max_position_amount >= 0",
            name="ck_system_risk_max_position_amount",
        ),
        sa.CheckConstraint(
            "max_position_count >= 0",
            name="ck_system_risk_max_position_count",
        ),
        sa.CheckConstraint(
            "max_position_weight >= 0 AND max_position_weight <= 1",
            name="ck_system_risk_max_position_weight",
        ),
        sa.CheckConstraint(
            "daily_max_loss_amount >= 0",
            name="ck_system_risk_daily_max_loss_amt",
        ),
        sa.CheckConstraint(
            "daily_max_loss_rate >= 0 AND daily_max_loss_rate <= 1",
            name="ck_system_risk_daily_max_loss_rate",
        ),
        sa.CheckConstraint(
            "stop_loss_rate >= 0 AND stop_loss_rate <= 1",
            name="ck_system_risk_stop_loss",
        ),
        sa.CheckConstraint(
            "take_profit_rate >= 0 AND take_profit_rate <= 1",
            name="ck_system_risk_take_profit",
        ),
        sa.CheckConstraint(
            "trailing_stop_rate IS NULL OR "
            "(trailing_stop_rate >= 0 AND trailing_stop_rate <= 1)",
            name="ck_system_risk_trailing",
        ),
        schema="trading",
    )

    # --- 사용자 기본 (필드 NULL = 시스템 상속) ---
    op.create_table(
        "user_risk_setting",
        sa.Column(
            "user_risk_setting_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("max_order_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column(
            "daily_max_order_amount", sa.Numeric(20, 2), nullable=True
        ),
        sa.Column(
            "max_total_investment_amount",
            sa.Numeric(20, 2),
            nullable=True,
        ),
        sa.Column("max_position_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("max_position_count", sa.Integer(), nullable=True),
        sa.Column("max_position_weight", sa.Numeric(10, 6), nullable=True),
        sa.Column("allow_duplicate_buy", sa.Boolean(), nullable=True),
        sa.Column(
            "daily_max_loss_amount", sa.Numeric(20, 2), nullable=True
        ),
        sa.Column("daily_max_loss_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("stop_loss_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("take_profit_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("trailing_stop_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("auto_trading_enabled", sa.Boolean(), nullable=True),
        sa.Column("buy_enabled", sa.Boolean(), nullable=True),
        sa.Column("sell_enabled", sa.Boolean(), nullable=True),
        sa.Column("sell_only", sa.Boolean(), nullable=True),
        sa.Column("account_paused", sa.Boolean(), nullable=True),
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
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("updated_by", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.user.user_id"],
            name="fk_user_risk_setting_user",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id", name="uq_user_risk_setting_user"
        ),
        sa.CheckConstraint(
            "max_order_amount IS NULL OR max_order_amount >= 0",
            name="ck_user_risk_max_order_amount",
        ),
        sa.CheckConstraint(
            "daily_max_order_amount IS NULL OR daily_max_order_amount >= 0",
            name="ck_user_risk_daily_max_order",
        ),
        sa.CheckConstraint(
            "max_total_investment_amount IS NULL OR "
            "max_total_investment_amount >= 0",
            name="ck_user_risk_max_total_invest",
        ),
        sa.CheckConstraint(
            "max_position_amount IS NULL OR max_position_amount >= 0",
            name="ck_user_risk_max_position_amount",
        ),
        sa.CheckConstraint(
            "max_position_count IS NULL OR max_position_count >= 0",
            name="ck_user_risk_max_position_count",
        ),
        sa.CheckConstraint(
            "max_position_weight IS NULL OR "
            "(max_position_weight >= 0 AND max_position_weight <= 1)",
            name="ck_user_risk_max_position_weight",
        ),
        sa.CheckConstraint(
            "daily_max_loss_amount IS NULL OR daily_max_loss_amount >= 0",
            name="ck_user_risk_daily_max_loss_amt",
        ),
        sa.CheckConstraint(
            "daily_max_loss_rate IS NULL OR "
            "(daily_max_loss_rate >= 0 AND daily_max_loss_rate <= 1)",
            name="ck_user_risk_daily_max_loss_rate",
        ),
        sa.CheckConstraint(
            "stop_loss_rate IS NULL OR "
            "(stop_loss_rate >= 0 AND stop_loss_rate <= 1)",
            name="ck_user_risk_stop_loss",
        ),
        sa.CheckConstraint(
            "take_profit_rate IS NULL OR "
            "(take_profit_rate >= 0 AND take_profit_rate <= 1)",
            name="ck_user_risk_take_profit",
        ),
        sa.CheckConstraint(
            "trailing_stop_rate IS NULL OR "
            "(trailing_stop_rate >= 0 AND trailing_stop_rate <= 1)",
            name="ck_user_risk_trailing",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_user_risk_setting_user_id",
        "user_risk_setting",
        ["user_id"],
        unique=False,
        schema="trading",
    )

    # --- 계좌별 (UBA) — NULL = 상위 상속 ---
    op.create_table(
        "user_broker_account_risk_setting",
        sa.Column(
            "user_broker_account_risk_setting_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column(
            "user_broker_account_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("max_order_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column(
            "daily_max_order_amount", sa.Numeric(20, 2), nullable=True
        ),
        sa.Column(
            "max_total_investment_amount",
            sa.Numeric(20, 2),
            nullable=True,
        ),
        sa.Column("max_position_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("max_position_count", sa.Integer(), nullable=True),
        sa.Column("max_position_weight", sa.Numeric(10, 6), nullable=True),
        sa.Column("allow_duplicate_buy", sa.Boolean(), nullable=True),
        sa.Column(
            "daily_max_loss_amount", sa.Numeric(20, 2), nullable=True
        ),
        sa.Column("daily_max_loss_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("stop_loss_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("take_profit_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("trailing_stop_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("auto_trading_enabled", sa.Boolean(), nullable=True),
        sa.Column("buy_enabled", sa.Boolean(), nullable=True),
        sa.Column("sell_enabled", sa.Boolean(), nullable=True),
        sa.Column("sell_only", sa.Boolean(), nullable=True),
        sa.Column("account_paused", sa.Boolean(), nullable=True),
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
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("updated_by", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_broker_account_id"],
            ["trading.user_broker_account.user_broker_account_id"],
            name="fk_uba_risk_setting_uba",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_broker_account_id",
            name="uq_uba_risk_setting_account",
        ),
        sa.CheckConstraint(
            "max_order_amount IS NULL OR max_order_amount >= 0",
            name="ck_uba_risk_max_order_amount",
        ),
        sa.CheckConstraint(
            "daily_max_order_amount IS NULL OR daily_max_order_amount >= 0",
            name="ck_uba_risk_daily_max_order",
        ),
        sa.CheckConstraint(
            "max_total_investment_amount IS NULL OR "
            "max_total_investment_amount >= 0",
            name="ck_uba_risk_max_total_invest",
        ),
        sa.CheckConstraint(
            "max_position_amount IS NULL OR max_position_amount >= 0",
            name="ck_uba_risk_max_position_amount",
        ),
        sa.CheckConstraint(
            "max_position_count IS NULL OR max_position_count >= 0",
            name="ck_uba_risk_max_position_count",
        ),
        sa.CheckConstraint(
            "max_position_weight IS NULL OR "
            "(max_position_weight >= 0 AND max_position_weight <= 1)",
            name="ck_uba_risk_max_position_weight",
        ),
        sa.CheckConstraint(
            "daily_max_loss_amount IS NULL OR daily_max_loss_amount >= 0",
            name="ck_uba_risk_daily_max_loss_amt",
        ),
        sa.CheckConstraint(
            "daily_max_loss_rate IS NULL OR "
            "(daily_max_loss_rate >= 0 AND daily_max_loss_rate <= 1)",
            name="ck_uba_risk_daily_max_loss_rate",
        ),
        sa.CheckConstraint(
            "stop_loss_rate IS NULL OR "
            "(stop_loss_rate >= 0 AND stop_loss_rate <= 1)",
            name="ck_uba_risk_stop_loss",
        ),
        sa.CheckConstraint(
            "take_profit_rate IS NULL OR "
            "(take_profit_rate >= 0 AND take_profit_rate <= 1)",
            name="ck_uba_risk_take_profit",
        ),
        sa.CheckConstraint(
            "trailing_stop_rate IS NULL OR "
            "(trailing_stop_rate >= 0 AND trailing_stop_rate <= 1)",
            name="ck_uba_risk_trailing",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_uba_risk_setting_uba_id",
        "user_broker_account_risk_setting",
        ["user_broker_account_id"],
        unique=False,
        schema="trading",
    )

    # Backfill: 시스템 기본 1행 (realtime_risk_policy 코드 기본과 정렬)
    op.execute(
        sa.text(
            """
            INSERT INTO trading.system_risk_setting (
                singleton_key,
                max_order_amount,
                daily_max_order_amount,
                max_total_investment_amount,
                max_position_amount,
                max_position_count,
                max_position_weight,
                allow_duplicate_buy,
                daily_max_loss_amount,
                daily_max_loss_rate,
                stop_loss_rate,
                take_profit_rate,
                trailing_stop_rate,
                auto_trading_enabled,
                buy_enabled,
                sell_enabled,
                sell_only,
                account_paused,
                created_by,
                updated_by
            )
            VALUES (
                'DEFAULT',
                100000,
                1000000,
                5000000,
                1000000,
                5,
                0.200000,
                true,
                300000,
                0.050000,
                0.050000,
                0.100000,
                0.030000,
                true,
                true,
                true,
                false,
                false,
                'MIGRATION_STEP8_2',
                'MIGRATION_STEP8_2'
            )
            ON CONFLICT (singleton_key) DO NOTHING
            """
        )
    )
    # strategy.risk_policy 활성 행이 있으면 stop/take/trailing/max positions 반영
    op.execute(
        sa.text(
            """
            UPDATE trading.system_risk_setting AS s
            SET
                stop_loss_rate = p.stop_loss_ratio,
                take_profit_rate = p.take_profit_ratio,
                trailing_stop_rate = p.trailing_stop_ratio,
                max_position_count = p.maximum_positions,
                max_position_weight = p.maximum_position_ratio,
                updated_by = 'MIGRATION_STEP8_2_RISK_POLICY'
            FROM (
                SELECT *
                FROM strategy.risk_policy
                WHERE is_active = true
                ORDER BY policy_id
                LIMIT 1
            ) AS p
            WHERE s.singleton_key = 'DEFAULT'
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_uba_risk_setting_uba_id",
        table_name="user_broker_account_risk_setting",
        schema="trading",
    )
    op.drop_table(
        "user_broker_account_risk_setting",
        schema="trading",
    )
    op.drop_index(
        "ix_user_risk_setting_user_id",
        table_name="user_risk_setting",
        schema="trading",
    )
    op.drop_table("user_risk_setting", schema="trading")
    op.drop_table("system_risk_setting", schema="trading")
