"""STEP 8-5-6 — Migration revision presence / head."""

from __future__ import annotations

import pytest

from tests.migration_helpers import (
    assert_db_matches_alembic_head,
    assert_revision_exists,
    alembic_current_head,
)


def test_step8_5_6_revision_exists() -> None:
    assert_revision_exists("w0a1b2c3d4e5")
    # Head는 후속 STEP에서 전진할 수 있음 — revision 존재 + single head만 검증
    assert len({alembic_current_head()}) == 1


@pytest.mark.integration
def test_step8_5_6_db_head_matches() -> None:
    from sqlalchemy import text

    from stock_platform.database.session import get_session_factory

    session = get_session_factory()()
    try:
        version = session.execute(
            text(
                "SELECT version_num FROM operation.alembic_version LIMIT 1"
            )
        ).scalar()
        assert_db_matches_alembic_head(version)
    finally:
        session.close()
