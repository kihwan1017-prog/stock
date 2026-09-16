"""STEP8-2 migration integration."""

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
def test_step8_2_risk_setting_tables_and_uniques() -> None:
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
            assert_revision_exists("q4e5f6a7b8c9")

            for table in (
                "system_risk_setting",
                "user_risk_setting",
                "user_broker_account_risk_setting",
            ):
                exists = conn.execute(
                    text(
                        """
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema='trading' AND table_name=:t
                        """
                    ),
                    {"t": table},
                ).scalar()
                assert exists == 1

            singleton = conn.execute(
                text(
                    """
                    SELECT COUNT(*)::int
                    FROM trading.system_risk_setting
                    WHERE singleton_key='DEFAULT'
                    """
                )
            ).scalar()
            assert singleton == 1

            # unique 제약 존재
            for name in (
                "uq_system_risk_setting_singleton",
                "uq_user_risk_setting_user",
                "uq_uba_risk_setting_account",
            ):
                found = conn.execute(
                    text(
                        "SELECT 1 FROM pg_constraint WHERE conname=:n"
                    ),
                    {"n": name},
                ).scalar()
                assert found == 1
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL 연결 불가: {exc}")
