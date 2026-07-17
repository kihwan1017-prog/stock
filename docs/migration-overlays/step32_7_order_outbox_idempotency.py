"""STEP32-7 order outbox and idempotency — overlay 참고용 (적용 금지)

canonical: database/alembic/versions/*_add_order_outbox_idempotency_execution_tables.py
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "step32_7"
down_revision = "REPLACE_WITH_PREVIOUS_REVISION"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_key",
        sa.Column(
            "idempotency_key",
            sa.String(length=200),
            primary_key=True,
        ),
        sa.Column(
            "request_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "status_code",
            sa.String(length=20),
            nullable=False,
            server_default="PROCESSING",
        ),
        sa.Column(
            "result_json",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="operation",
    )

    op.create_table(
        "order_outbox",
        sa.Column(
            "outbox_id",
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
            "event_type",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=200),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "payload_json",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "status_code",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "max_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "locked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "locked_by",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "last_error",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="trading",
    )

    op.create_index(
        "ix_order_outbox_claim",
        "order_outbox",
        [
            "status_code",
            "next_retry_at",
            "outbox_id",
        ],
        schema="trading",
    )
    op.create_index(
        "ix_order_outbox_order_id",
        "order_outbox",
        ["order_id"],
        schema="trading",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_order_outbox_order_id",
        table_name="order_outbox",
        schema="trading",
    )
    op.drop_index(
        "ix_order_outbox_claim",
        table_name="order_outbox",
        schema="trading",
    )
    op.drop_table(
        "order_outbox",
        schema="trading",
    )
    op.drop_table(
        "idempotency_key",
        schema="operation",
    )
