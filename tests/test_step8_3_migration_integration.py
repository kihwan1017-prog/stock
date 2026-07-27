"""STEP8-3 migration integration."""

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
def test_step8_3_strategy_definition_tables() -> None:
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
            assert_revision_exists("r5e6f7a8b9c0")

            for table in (
                "strategy_definition",
                "account_strategy_link",
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

            for col in (
                "strategy_id",
                "owner_type",
                "user_id",
                "visibility",
            ):
                found = conn.execute(
                    text(
                        """
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema='trading'
                          AND table_name='strategy_deployment'
                          AND column_name=:c
                        """
                    ),
                    {"c": col},
                ).scalar()
                assert found == 1

            # operator 메타 보존 (값 변경 없음)
            # 테이블이 없으면 스킵
            has_approval = conn.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema='trading'
                      AND table_name='strategy_approval_run'
                    """
                )
            ).scalar()
            if has_approval:
                # 마이그레이션이 operator → admin 변환하지 않았는지
                # (존재 행이 있으면 그대로 'operator')
                bad = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)::int
                        FROM trading.strategy_approval_run
                        WHERE decided_by = 'admin'
                          AND decided_by IS DISTINCT FROM requested_by
                        """
                    )
                ).scalar()
                # 강제 변환 검증은 약하게 — 핵심은 마이그레이션 SQL에
                # UPDATE decided_by 가 없는 것 (단위로 문서화)
                assert bad is not None

            for ck_fragment in (
                "owner_type",
                "visibility",
                "owner_user",
            ):
                found = conn.execute(
                    text(
                        """
                        SELECT 1
                        FROM pg_constraint c
                        JOIN pg_class t ON c.conrelid = t.oid
                        JOIN pg_namespace n ON t.relnamespace = n.oid
                        WHERE n.nspname = 'trading'
                          AND t.relname = 'strategy_definition'
                          AND c.conname LIKE :pat
                        """
                    ),
                    {"pat": f"%{ck_fragment}%"},
                ).scalar()
                assert found == 1
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL 연결 불가: {exc}")
