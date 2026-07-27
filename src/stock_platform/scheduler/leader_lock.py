"""다중 API 인스턴스 cron 중복 방지용 PostgreSQL advisory lock.

연결을 유지하는 동안만 락이 유효하다. 리더가 죽으면 연결이 끊기며 락이 해제된다.
SQLite 등 비-PG 환경에서는 항상 리더로 간주한다 (로컬/테스트).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


# 프로젝트 전용 고정 키 (다른 advisory lock과 충돌 피함)
LIFECYCLE_SCHEDULER_LOCK_KEY = 82_024_090_1


@dataclass(slots=True)
class SchedulerLeaderLock:
    """획득한 리더 락. shutdown 시 release() 호출."""

    connection: Connection | None
    acquired: bool
    reason: str

    def release(self) -> None:
        if self.connection is None:
            return
        try:
            if self.acquired:
                self.connection.execute(
                    text(
                        "SELECT pg_advisory_unlock(:key)"
                    ),
                    {"key": LIFECYCLE_SCHEDULER_LOCK_KEY},
                )
                self.connection.commit()
        except Exception:
            pass
        finally:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None
            self.acquired = False


def try_acquire_lifecycle_scheduler_lock(
    engine: Engine,
) -> SchedulerLeaderLock:
    """lifecycle cron 리더 선출. 실패 시 acquired=False."""

    dialect = engine.dialect.name
    if dialect != "postgresql":
        return SchedulerLeaderLock(
            connection=None,
            acquired=True,
            reason=f"non_postgres_dialect:{dialect}",
        )

    connection = engine.connect()
    try:
        # 트랜잭션 밖에서도 유지되는 session-level advisory lock
        connection = connection.execution_options(
            isolation_level="AUTOCOMMIT"
        )
        row = connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": LIFECYCLE_SCHEDULER_LOCK_KEY},
        ).scalar()
        if bool(row):
            return SchedulerLeaderLock(
                connection=connection,
                acquired=True,
                reason="pg_try_advisory_lock",
            )
        connection.close()
        return SchedulerLeaderLock(
            connection=None,
            acquired=False,
            reason="lock_held_by_other_instance",
        )
    except Exception as exc:
        try:
            connection.close()
        except Exception:
            pass
        # 락 확인 실패 시 fail-open(단일 노드 운영 유지) — 다중 노드에서는 플래그로 차단 권장
        return SchedulerLeaderLock(
            connection=None,
            acquired=True,
            reason=f"lock_check_failed:{exc}",
        )
