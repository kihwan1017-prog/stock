"""STEP 8-5-22-DBA-FIX Alembic operation/platform schema bootstrap."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import ProgrammingError

from database.alembic.bootstrap import (
    ALEMBIC_VERSION_SCHEMA,
    PLATFORM_SCHEMAS,
    emit_platform_schema_sql,
    ensure_operation_schema,
    ensure_platform_schemas,
)
from tests.migration_helpers import alembic_current_head


def test_ensure_operation_schema_idempotent_postgresql() -> None:
    connection = MagicMock()
    connection.dialect.name = "postgresql"
    connection.execute.return_value = MagicMock()

    ensure_operation_schema(connection)

    assert connection.execute.call_count == len(PLATFORM_SCHEMAS)
    sqls = [str(c[0][0]) for c in connection.execute.call_args_list]
    assert any("CREATE SCHEMA IF NOT EXISTS" in s and "operation" in s for s in sqls)
    assert any("market" in s for s in sqls)
    connection.commit.assert_called()


def test_ensure_operation_schema_skips_non_postgres() -> None:
    connection = MagicMock()
    connection.dialect.name = "sqlite"
    ensure_platform_schemas(connection)
    connection.execute.assert_not_called()


def test_ensure_operation_schema_fail_closed_no_secret() -> None:
    connection = MagicMock()
    connection.dialect.name = "postgresql"

    def _exec(stmt, *args, **kwargs):
        text = str(stmt)
        if "CREATE SCHEMA" in text:
            raise ProgrammingError(
                "CREATE SCHEMA",
                {},
                Exception("permission denied for database"),
            )
        result = MagicMock()
        result.scalar.return_value = "stock_app"
        return result

    connection.execute.side_effect = _exec

    with pytest.raises(RuntimeError) as exc:
        ensure_platform_schemas(connection)

    msg = str(exc.value)
    assert "operation" in msg
    assert "stock_app" in msg
    assert "password" not in msg.lower()
    assert "postgresql+psycopg://" not in msg.lower()


def test_version_table_schema_is_operation() -> None:
    assert ALEMBIC_VERSION_SCHEMA == "operation"
    assert "operation" in PLATFORM_SCHEMAS
    assert "market" in PLATFORM_SCHEMAS


def test_emit_platform_schema_sql_includes_operation_first_group() -> None:
    stmts = emit_platform_schema_sql()
    assert stmts[0].startswith("CREATE SCHEMA IF NOT EXISTS ")
    assert any(s.endswith("operation") for s in stmts)
    assert any(s.endswith("market") for s in stmts)


def test_ops_db_head_unchanged() -> None:
    assert alembic_current_head() == "ae5f6a7b8c9d"


def test_ensure_operation_schema_on_live_connection() -> None:
    """Idempotent CREATE SCHEMA IF NOT EXISTS on live DB connection."""

    from sqlalchemy import create_engine, text

    from stock_platform.common.settings import get_settings

    engine = create_engine(get_settings().database_url)
    with engine.connect() as conn:
        ensure_platform_schemas(conn)
        exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.schemata "
                "WHERE schema_name = 'operation'"
            )
        ).scalar()
        assert exists == 1
        ver = conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'operation' "
                "AND table_name = 'alembic_version'"
            )
        ).scalar()
        assert ver == 1
        # Version table must exist exactly once (no duplicates)
        cnt = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name = 'alembic_version'"
            )
        ).scalar()
        assert cnt == 1


def test_offline_sql_emits_operation_schema_first() -> None:
    """Offline SQL must emit platform schemas before the version table.

    Full head --sql is not offline-safe (fetchall), so we validate only the
    first revision span (existing contract, bootstrap ordering check).
    """

    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "21ef733dc7ca",
            "--sql",
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    out = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, out[-800:]
    upper = out.upper()
    assert "CREATE SCHEMA IF NOT EXISTS OPERATION" in upper
    assert "CREATE SCHEMA IF NOT EXISTS MARKET" in upper
    assert upper.index("CREATE SCHEMA IF NOT EXISTS OPERATION") < upper.index(
        "CREATE TABLE OPERATION.ALEMBIC_VERSION"
    )


def test_env_py_wires_bootstrap_before_configure() -> None:
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1]
        / "database"
        / "alembic"
        / "env.py"
    ).read_text(encoding="utf-8")
    assert "ensure_platform_schemas(connection)" in text
    assert "version_table_schema=ALEMBIC_VERSION_SCHEMA" in text
    online = text.split("def run_migrations_online")[1]
    assert online.index("ensure_platform_schemas") < online.index(
        "context.configure"
    )
