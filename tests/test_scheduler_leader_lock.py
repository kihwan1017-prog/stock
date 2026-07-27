"""STEP9 — scheduler leader lock / 계약 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

from stock_platform.scheduler.leader_lock import (
    LIFECYCLE_SCHEDULER_LOCK_KEY,
    try_acquire_lifecycle_scheduler_lock,
)


def test_non_postgres_dialect_is_always_leader() -> None:
    engine = MagicMock()
    engine.dialect.name = "sqlite"
    lock = try_acquire_lifecycle_scheduler_lock(engine)
    assert lock.acquired is True
    assert "non_postgres" in lock.reason
    lock.release()


def test_postgres_lock_acquired() -> None:
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = MagicMock()
    connection.execution_options.return_value = connection
    connection.execute.return_value.scalar.return_value = True
    engine.connect.return_value = connection

    lock = try_acquire_lifecycle_scheduler_lock(engine)
    assert lock.acquired is True
    assert lock.connection is connection
    connection.execute.assert_called()
    lock.release()
    assert lock.connection is None


def test_postgres_lock_not_acquired() -> None:
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = MagicMock()
    connection.execution_options.return_value = connection
    connection.execute.return_value.scalar.return_value = False
    engine.connect.return_value = connection

    lock = try_acquire_lifecycle_scheduler_lock(engine)
    assert lock.acquired is False
    assert lock.reason == "lock_held_by_other_instance"
    connection.close.assert_called_once()


def test_lock_key_is_stable() -> None:
    assert LIFECYCLE_SCHEDULER_LOCK_KEY == 82_024_090_1
