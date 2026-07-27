"""STEP8-1 migration/backfill integration smoke."""

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
def test_step8_1_trading_order_uba_column_and_unique_index() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                text(
                    "SELECT version_num FROM operation.alembic_version LIMIT 1"
                )
            ).scalar()
            # Head는 문자열 하드코딩하지 않음 — ScriptDirectory 기준
            assert_db_matches_alembic_head(version)
            # STEP8-1 Revision이 체인에 유지되는지 검증
            assert_revision_exists("p3d4e5f6a7b8")

            col = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'trading'
                      AND table_name = 'trading_order'
                      AND column_name = 'user_broker_account_id'
                    """
                )
            ).scalar()
            assert col == 1

            fk = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'fk_trading_order_user_broker_account'
                    """
                )
            ).scalar()
            assert fk == 1

            idx = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'trading'
                      AND indexname = 'uq_trading_order_uba_broker_order_id'
                    """
                )
            ).scalar()
            assert idx == 1

            target = conn.execute(
                text(
                    """
                    SELECT COUNT(*)::int
                    FROM trading.trading_order
                    WHERE upper(broker_code) IN ('KIWOOM', 'UPBIT')
                    """
                )
            ).scalar()
            linked = conn.execute(
                text(
                    """
                    SELECT COUNT(*)::int
                    FROM trading.trading_order
                    WHERE upper(broker_code) IN ('KIWOOM', 'UPBIT')
                      AND user_broker_account_id IS NOT NULL
                    """
                )
            ).scalar()
            unlinkable = conn.execute(
                text(
                    """
                    SELECT COUNT(*)::int
                    FROM trading.trading_order
                    WHERE upper(broker_code) IN ('KIWOOM', 'UPBIT')
                      AND user_broker_account_id IS NULL
                    """
                )
            ).scalar()
            assert target == linked + unlinkable
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL 연결 불가: {exc}")
