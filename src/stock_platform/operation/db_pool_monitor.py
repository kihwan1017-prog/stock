"""DB 연결·풀·세션 관측 (STEP61). 자동매매 로직 미변경."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text

from stock_platform.database.session import get_engine


def _pool_stats() -> dict[str, Any]:
    engine = get_engine()
    pool = engine.pool
    # QueuePool 기준 속성 (NullPool 등은 getattr 폴백)
    return {
        "pool_class": type(pool).__name__,
        "pool_size": getattr(pool, "size", lambda: None)()
        if callable(getattr(pool, "size", None))
        else getattr(pool, "size", None),
        "checked_in": getattr(pool, "checkedin", lambda: None)()
        if callable(getattr(pool, "checkedin", None))
        else None,
        "checked_out": getattr(pool, "checkedout", lambda: None)()
        if callable(getattr(pool, "checkedout", None))
        else None,
        "overflow": getattr(pool, "overflow", lambda: None)()
        if callable(getattr(pool, "overflow", None))
        else None,
        "max_overflow": getattr(pool, "_max_overflow", None),
    }


def measure_db_latency_ms() -> tuple[str, float | None, str | None]:
    """SELECT 1 왕복 시간(ms)."""

    started = time.perf_counter()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return "UP", round(elapsed_ms, 2), None
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return "DOWN", round(elapsed_ms, 2), str(exc)[:200]


def _pg_activity_stats() -> dict[str, Any]:
    """PostgreSQL 활성 세션·느린 쿼리 근사 (권한 없으면 skip)."""

    try:
        with get_engine().connect() as conn:
            active = conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE state = 'active' AND pid <> pg_backend_pid()"
                )
            ).scalar()
            # 5초 이상 실행 중이면 slow 근사
            slow = conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE state = 'active' "
                    "AND now() - query_start > interval '5 seconds' "
                    "AND pid <> pg_backend_pid()"
                )
            ).scalar()
            # xact rollback 누적 (인스턴스 시작 이후)
            rollbacks = conn.execute(
                text(
                    "SELECT sum(xact_rollback)::bigint "
                    "FROM pg_stat_database "
                    "WHERE datname = current_database()"
                )
            ).scalar()
        return {
            "active_sessions": int(active or 0),
            "slow_query_count": int(slow or 0),
            "transaction_rollbacks": int(rollbacks or 0),
            "source": "pg_stat",
        }
    except Exception as exc:
        return {
            "active_sessions": None,
            "slow_query_count": None,
            "transaction_rollbacks": None,
            "source": "unavailable",
            "message": str(exc)[:160],
        }


def build_database_monitoring() -> dict[str, Any]:
    status, latency_ms, error = measure_db_latency_ms()
    payload: dict[str, Any] = {
        "status": status,
        "response_time_ms": latency_ms,
        "connection_pool": _pool_stats(),
        **_pg_activity_stats(),
    }
    if error:
        payload["message"] = error
    return payload
