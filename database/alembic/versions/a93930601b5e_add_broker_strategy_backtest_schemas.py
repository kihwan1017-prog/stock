"""add broker strategy backtest schemas

Revision ID: a93930601b5e
Revises: 2b253a0771f8
Create Date: 2026-07-12 15:42:55.724166

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = 'a93930601b5e'
down_revision: Union[str, Sequence[str], None] = '21ef733dc7ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS broker AUTHORIZATION stock_app")
    op.execute("CREATE SCHEMA IF NOT EXISTS strategy AUTHORIZATION stock_app")
    op.execute("CREATE SCHEMA IF NOT EXISTS backtest AUTHORIZATION stock_app")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS backtest")
    op.execute("DROP SCHEMA IF EXISTS strategy")
    op.execute("DROP SCHEMA IF EXISTS broker")