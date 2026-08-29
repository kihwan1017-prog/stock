"""revision: tav2a1b2c3d4e
Trading Alert Management V2 — delivery preference table.

NOTIFICATION ONLY. Does not alter trading semantics.
Revises: ess1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "tav2a1b2c3d4e"
down_revision: Union[str, Sequence[str], None] = "ess1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULTS = [
    ("UPBIT_RUNTIME", True, "업비트 Runtime 시작/중지/복구"),
    ("UPBIT_AUTO_BUY", True, "업비트 AUTO 매수 체결"),
    ("UPBIT_AUTO_SELL", True, "업비트 AUTO 매도 체결"),
    ("UPBIT_ORDER_EXCEPTION", True, "업비트 주문/체결 이상"),
    ("KIWOOM_RUNTIME", True, "키움 Runtime 시작/중지/복구"),
    ("KIWOOM_AUTO_BUY", True, "키움 AUTO 매수 체결"),
    ("KIWOOM_AUTO_SELL", True, "키움 AUTO 매도 체결"),
    ("KIWOOM_ORDER_EXCEPTION", True, "키움 주문/체결 이상"),
    ("UPBIT_AI_DECISION", True, "UPBIT AI 판단 변경"),
    ("KIWOOM_AI_DECISION", True, "KIWOOM AI 판단 변경"),
    ("AUTO_SLOT", True, "자동매매 슬롯 lifecycle"),
    ("CANDIDATE_ANALYSIS", False, "후보 분석 요약"),
    ("SHADOW_ANALYSIS", False, "Shadow 연구 checkpoint"),
    ("SYSTEM_OPERATION", True, "시스템 중요 알림"),
]


def upgrade() -> None:
    op.create_table(
        "trading_alert_preference",
        sa.Column("preference_key", sa.String(length=64), primary_key=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", sa.String(length=80), nullable=True),
        schema="notification",
    )
    pref = sa.table(
        "trading_alert_preference",
        sa.column("preference_key", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("description", sa.Text),
        schema="notification",
    )
    op.bulk_insert(
        pref,
        [
            {
                "preference_key": key,
                "enabled": enabled,
                "description": desc,
            }
            for key, enabled, desc in _DEFAULTS
        ],
    )


def downgrade() -> None:
    op.drop_table("trading_alert_preference", schema="notification")
