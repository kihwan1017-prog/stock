"""merge current platform heads

Revision ID: a8105aa410f9
Revises: ntpl_ko_20260821a, perf_acs_obs_20260825, symown_20260821a
Create Date: 2026-08-25 22:13:39.067317

Graph-only merge — no DDL.
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "a8105aa410f9"
down_revision: Union[str, Sequence[str], None] = (
    "ntpl_ko_20260821a",
    "perf_acs_obs_20260825",
    "symown_20260821a",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
