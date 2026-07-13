"""rename instrument asset type constraint

Revision ID: 3d46460efdbb
Revises: 63974784f82a
Create Date: 2026-07-13 20:56:46.409294

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d46460efdbb'
down_revision: Union[str, Sequence[str], None] = '63974784f82a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE market.instrument
        RENAME CONSTRAINT ck_instrument_ck_instrument_asset_type
        TO ck_instrument_asset_type
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE market.instrument
        RENAME CONSTRAINT ck_instrument_asset_type
        TO ck_instrument_ck_instrument_asset_type
        """
    )
