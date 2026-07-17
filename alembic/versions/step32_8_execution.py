"""STEP32-8 trading execution

Revision ID: step32_8
Revises: step32_7
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "step32_8"
down_revision = "step32_7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution",
        sa.Column(
            "execution_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "order_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "trading.trading_order.order_id"
            ),
            nullable=False,
        ),
        sa.Column(
            "broker_code",
            sa.String(length=20),
            nullable=False,
            server_default="KIWOOM",
        ),
        sa.Column(
            "broker_order_id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "broker_execution_id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "symbol",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "side_code",
            sa.String(length=20),
            nullable=True,
        ),
        sa.Column(
            "execution_price",
            sa.Numeric(20, 8),
            nullable=False,
        ),
        sa.Column(
            "execution_quantity",
            sa.Numeric(20, 8),
            nullable=False,
        ),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "raw_json",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "broker_code",
            "broker_execution_id",
            name=(
                "uq_execution_broker_execution"
            ),
        ),
        schema="trading",
    )

    op.create_index(
        "ix_execution_order_id",
        "execution",
        ["order_id"],
        schema="trading",
    )
    op.create_index(
        "ix_execution_executed_at",
        "execution",
        ["executed_at"],
        schema="trading",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_execution_executed_at",
        table_name="execution",
        schema="trading",
    )
    op.drop_index(
        "ix_execution_order_id",
        table_name="execution",
        schema="trading",
    )
    op.drop_table(
        "execution",
        schema="trading",
    )
