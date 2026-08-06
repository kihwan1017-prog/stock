"""Allow LIVE trading_order without paper account_id (UBA XOR)

Revision ID: j4k5l6m7n8o9
Revises: i2j3k4l5m6n7

LIVE 주문은 user_broker_account_id 만 사용하고
paper FK 슬롯(account_id)은 NULL 이어야 한다.

기존 행(둘 다 세팅된 LIVE placeholder)은 backfill 하지 않으며,
CHECK 는 NOT VALID 로 추가해 신규 INSERT/UPDATE 만 강제한다.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "j4k5l6m7n8o9"
down_revision: Union[str, Sequence[str], None] = "i2j3k4l5m6n7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHECK_NAME = "ck_trading_order_account_xor"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE trading.trading_order "
        "ALTER COLUMN account_id DROP NOT NULL"
    )
    op.execute(
        f"""
        ALTER TABLE trading.trading_order
        ADD CONSTRAINT {_CHECK_NAME}
        CHECK (
            (
                account_id IS NOT NULL
                AND user_broker_account_id IS NULL
            )
            OR (
                account_id IS NULL
                AND user_broker_account_id IS NOT NULL
            )
        ) NOT VALID
        """
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE trading.trading_order "
        f"DROP CONSTRAINT IF EXISTS {_CHECK_NAME}"
    )
    # NULL account_id 가 있으면 NOT NULL 복구 실패 — 의도된 가드
    op.execute(
        "ALTER TABLE trading.trading_order "
        "ALTER COLUMN account_id SET NOT NULL"
    )
