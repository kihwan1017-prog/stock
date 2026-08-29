"""UPBIT Short-Term Operation V1 — daily ENTRY limit=6 for portfolio policy.

Canonical SoT: operation.upbit_portfolio_policy.portfolio_daily_entry_limit
(ENTRY BUY only; SELL never counts — existing count semantics).

Does NOT change trading.user_broker_account_risk_setting.daily_order_limit
(legacy V1 CREATE semantics retained for non-UPBIT-AUTO paths).

Revises: h2h3fs1a2b3c4d
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sto1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "h2h3fs1a2b3c4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# UPBIT_SHORT_TERM_OPERATION_V1
_TARGET_UBA_ID = 1380
_NEW_LIMIT = 6
_PREV_LIMIT = 20


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE operation.upbit_portfolio_policy
               SET portfolio_daily_entry_limit = :new_limit,
                   updated_at = NOW()
             WHERE user_broker_account_id = :uba_id
            """
        ),
        {"new_limit": _NEW_LIMIT, "uba_id": _TARGET_UBA_ID},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE operation.upbit_portfolio_policy
               SET portfolio_daily_entry_limit = :prev_limit,
                   updated_at = NOW()
             WHERE user_broker_account_id = :uba_id
               AND portfolio_daily_entry_limit = :new_limit
            """
        ),
        {
            "prev_limit": _PREV_LIMIT,
            "new_limit": _NEW_LIMIT,
            "uba_id": _TARGET_UBA_ID,
        },
    )
