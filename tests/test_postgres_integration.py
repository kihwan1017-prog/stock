"""진짜 PostgreSQL integration 스모크 (P1)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from stock_platform.common.settings import get_settings


@pytest.mark.integration
def test_postgres_alembic_head_and_paper_order_account_fk() -> None:
    """DB 연결 + alembic head + paper_order.account_id FK 존재."""

    settings = get_settings()
    url = settings.database_url
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                text(
                    "SELECT version_num "
                    "FROM operation.alembic_version "
                    "LIMIT 1"
                )
            ).scalar()
            assert version is not None

            has_account = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'trading'
                      AND table_name = 'paper_order'
                      AND column_name = 'account_id'
                    """
                )
            ).scalar()
            assert has_account == 1

            fk = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'fk_paper_order_account'
                    """
                )
            ).scalar()
            assert fk == 1
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL 연결 불가: {exc}")
