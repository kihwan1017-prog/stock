"""STEP8-4 migration integration."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from stock_platform.common.settings import get_settings
from tests.migration_helpers import (
    assert_db_matches_alembic_head,
    assert_revision_exists,
)


@pytest.mark.integration
def test_step8_4_recovery_tables() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                text(
                    "SELECT version_num FROM operation.alembic_version LIMIT 1"
                )
            ).scalar()
            assert_db_matches_alembic_head(version)
            assert_revision_exists("s6f7a8b9c0d1")

            exists = conn.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema='operation'
                      AND table_name='broker_recovery_account_state'
                    """
                )
            ).scalar()
            assert exists == 1

            for col in (
                "trigger_type",
                "broker_code",
                "user_id",
                "conflicts_found",
            ):
                found = conn.execute(
                    text(
                        """
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema='operation'
                          AND table_name='broker_recovery_run'
                          AND column_name=:c
                        """
                    ),
                    {"c": col},
                ).scalar()
                assert found == 1
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL 연결 불가: {exc}")
