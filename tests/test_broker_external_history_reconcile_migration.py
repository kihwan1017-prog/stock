"""Focused tests: broker external history reconciliation migration graph/idempotency."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tests.migration_helpers import (
    alembic_current_head,
    alembic_script_directory,
    assert_revision_exists,
    assert_revision_is_ancestor_of_head,
)

NEW_REV = "l3m4n5o6p7q8"
PARENT_REV = "k2l3m4n5o6p7"
QUARANTINED_REV = "h1a2b3c4d5e6"


def test_external_history_reconcile_is_single_head_child_of_k2() -> None:
    script = alembic_script_directory()
    heads = script.get_heads()
    assert heads == [NEW_REV], f"expected single head {NEW_REV}, got {heads}"
    assert alembic_current_head() == NEW_REV

    rev = script.get_revision(NEW_REV)
    assert rev is not None
    assert rev.down_revision == PARENT_REV

    assert_revision_exists(NEW_REV)
    assert_revision_is_ancestor_of_head(PARENT_REV)


def test_quarantined_h1a_not_in_active_versions_graph() -> None:
    script = alembic_script_directory()
    revisions = {r.revision for r in script.walk_revisions()}
    assert QUARANTINED_REV not in revisions

    versions_dir = (
        Path(__file__).resolve().parents[1]
        / "database"
        / "alembic"
        / "versions"
    )
    leftover = list(versions_dir.glob(f"{QUARANTINED_REV}_*.py"))
    assert leftover == [], f"quarantined revision leaked into versions: {leftover}"

    quarantine = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "audit"
        / "quarantined_migrations"
        / f"{QUARANTINED_REV}_broker_external_order_history.py"
    )
    assert quarantine.is_file()


def test_upgrade_idempotent_on_existing_and_fresh_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PostgreSQL 임시 스키마에서 create → 재실행(idempotent) 검증."""
    try:
        from stock_platform.common.settings import get_settings

        url = get_settings().database_url
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"settings/database unavailable: {exc}")

    if not url or "postgres" not in str(url).lower():
        pytest.skip("PostgreSQL database_url required")

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    import database.alembic.versions.l3m4n5o6p7q8_broker_external_history_reconcile as mig

    engine = create_engine(url)
    schema = "tmp_ext_hist_recon_l3"
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))

    # migration 모듈의 schema 상수를 임시 스키마로 치환
    monkeypatch.setattr(mig, "_SCHEMA", schema)

    try:
        with engine.begin() as conn:
            mc = MigrationContext.configure(conn)
            with Operations.context(mc):
                mig.upgrade()
                assert mig._has_table(mig._ORDER_TABLE)
                assert mig._has_table(mig._TRADE_TABLE)
                # idempotent 재실행 — DuplicateTable 없어야 함
                mig.upgrade()
                assert mig._has_table(mig._ORDER_TABLE)
                assert "ix_broker_ext_order_uba" in mig._index_names(
                    mig._ORDER_TABLE
                )
                assert "ix_broker_ext_trade_order" in mig._index_names(
                    mig._TRADE_TABLE
                )
                order_n = conn.execute(
                    text(f"SELECT COUNT(*) FROM {schema}.{mig._ORDER_TABLE}")
                ).scalar()
                trade_n = conn.execute(
                    text(f"SELECT COUNT(*) FROM {schema}.{mig._TRADE_TABLE}")
                ).scalar()
                assert int(order_n or 0) == 0
                assert int(trade_n or 0) == 0
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
