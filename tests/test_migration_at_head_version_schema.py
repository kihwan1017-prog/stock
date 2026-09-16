"""health checker 가 operation.alembic_version 을 보도록 고정한다.

과거 MigrationContext.configure(conn) 만 호출하면 public.alembic_version 을
찾아 MIGRATION_NOT_AT_HEAD 가 났다. 실제 version table 은 operation 스키마다.
이 테스트는 Alembic upgrade 를 실행하지 않는다.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from database.alembic.bootstrap import ALEMBIC_VERSION_SCHEMA
from stock_platform.operation.startup_runtime_policy import migration_at_head


def test_alembic_version_schema_constant_is_operation() -> None:
    assert ALEMBIC_VERSION_SCHEMA == "operation"


def test_migration_at_head_configures_operation_version_schema() -> None:
    session = MagicMock()
    conn = MagicMock()
    session.connection.return_value = conn

    script = MagicMock()
    script.get_current_head.return_value = "egv2a1b2c3d4"
    context = MagicMock()
    context.get_current_revision.return_value = "egv2a1b2c3d4"

    with (
        patch(
            "alembic.script.ScriptDirectory.from_config",
            return_value=script,
        ),
        patch(
            "alembic.runtime.migration.MigrationContext.configure",
            return_value=context,
        ) as configure,
    ):
        assert migration_at_head(session) is True

    configure.assert_called_once()
    _args, kwargs = configure.call_args
    opts = kwargs.get("opts") or {}
    assert opts.get("version_table") == "alembic_version"
    assert opts.get("version_table_schema") == ALEMBIC_VERSION_SCHEMA
    assert opts.get("version_table_schema") == "operation"


def test_migration_at_head_false_when_revision_differs() -> None:
    session = MagicMock()
    session.connection.return_value = MagicMock()

    script = MagicMock()
    script.get_current_head.return_value = "egv2a1b2c3d4"
    context = MagicMock()
    context.get_current_revision.return_value = None

    with (
        patch(
            "alembic.script.ScriptDirectory.from_config",
            return_value=script,
        ),
        patch(
            "alembic.runtime.migration.MigrationContext.configure",
            return_value=context,
        ),
    ):
        assert migration_at_head(session) is False


def test_migration_at_head_fail_closed_on_error() -> None:
    session = MagicMock()
    session.connection.side_effect = RuntimeError("db unavailable")
    assert migration_at_head(session) is False
