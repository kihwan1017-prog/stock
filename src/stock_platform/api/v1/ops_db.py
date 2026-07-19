from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session
from stock_platform.operation.health_service import check_database


router = APIRouter(
    prefix="/api/v1/ops",
    tags=["Operations"],
)


def _project_root() -> Path:
    # src/stock_platform/api/v1/ops_db.py → repo root
    return Path(__file__).resolve().parents[4]


def _alembic_heads() -> list[str]:
    ini_path = _project_root() / "alembic.ini"
    config = Config(str(ini_path))
    script = ScriptDirectory.from_config(config)
    return list(script.get_heads())


def _current_revision(session: Session) -> str | None:
    try:
        row = session.execute(
            text(
                "SELECT version_num "
                "FROM operation.alembic_version "
                "LIMIT 1"
            )
        ).scalar()
        return str(row) if row else None
    except Exception:
        session.rollback()
        return None


@router.get("/db/status")
def get_db_status(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(
        require_permission("system:read")
    ),
):
    """DB 연결·스키마·테이블 수 요약 (읽기 전용)."""

    health = check_database()
    schemas: list[dict[str, Any]] = []
    try:
        rows = session.execute(
            text(
                """
                SELECT table_schema, COUNT(*) AS table_count
                FROM information_schema.tables
                WHERE table_schema IN (
                    'auth', 'broker', 'market', 'operation',
                    'strategy', 'trading', 'backtest', 'common',
                    'disclosure', 'news', 'ai'
                )
                AND table_type = 'BASE TABLE'
                GROUP BY table_schema
                ORDER BY table_schema
                """
            )
        ).mappings()
        schemas = [dict(row) for row in rows]
    except Exception as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"스키마 조회 실패: {exc}",
        ) from exc

    settings = get_settings()
    return {
        "status": health.get("status"),
        "checked_at": datetime.now(timezone.utc),
        "database": {
            "host": settings.db_host,
            "port": settings.db_port,
            "name": settings.db_name,
            "user": settings.db_user,
        },
        "schemas": schemas,
        "health": health,
    }


@router.get("/db/migration-status")
def get_migration_status(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(
        require_permission("system:read")
    ),
):
    """Alembic current vs head (읽기 전용, upgrade 실행 없음)."""

    try:
        heads = _alembic_heads()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Alembic head 조회 실패: {exc}",
        ) from exc

    current = _current_revision(session)
    in_sync = current is not None and current in heads
    return {
        "current": current,
        "heads": heads,
        "in_sync": in_sync,
        "upgrade_command": "python -m alembic upgrade head",
        "checked_at": datetime.now(timezone.utc),
    }


@router.get("/db/tables")
def list_db_tables(
    schema: str = Query(default="trading", max_length=64),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(
        require_permission("system:read")
    ),
):
    """스키마별 테이블 목록 (읽기 전용)."""

    allowed = {
        "auth",
        "broker",
        "market",
        "operation",
        "strategy",
        "trading",
        "backtest",
        "common",
        "disclosure",
        "news",
        "ai",
    }
    if schema not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"허용 schema: {sorted(allowed)}",
        )

    rows = session.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = :schema
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        ),
        {"schema": schema},
    ).scalars()
    return {
        "schema": schema,
        "tables": [str(name) for name in rows],
    }


@router.get("/backup/status")
def get_backup_tool_status(
    _: AuthenticatedUser = Depends(
        require_permission("ops:execute")
    ),
):
    """pg_dump/pg_restore 도구 가용성 점검 (실행·복구 아님)."""

    settings = get_settings()
    pg_dump = shutil.which("pg_dump")
    pg_restore = shutil.which("pg_restore")
    psql = shutil.which("psql")

    dump_version: str | None = None
    if pg_dump:
        try:
            completed = subprocess.run(
                [pg_dump, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            dump_version = (
                completed.stdout.strip()
                or completed.stderr.strip()
                or None
            )
        except Exception as exc:
            dump_version = f"version check failed: {exc}"

    backup_dir = Path(r"E:\StockTrading\backups")
    return {
        "pg_dump_path": pg_dump,
        "pg_restore_path": pg_restore,
        "psql_path": psql,
        "pg_dump_version": dump_version,
        "tools_ready": bool(pg_dump and pg_restore),
        "recommended_backup_dir": str(backup_dir),
        "backup_dir_exists": backup_dir.exists(),
        "database": {
            "host": settings.db_host,
            "port": settings.db_port,
            "name": settings.db_name,
        },
        "manual": "docs/manual/백업복구매뉴얼.md",
        "example_command": (
            "pg_dump -h $env:DB_HOST -p $env:DB_PORT "
            "-U $env:DB_USER -d $env:DB_NAME -Fc "
            "-f E:\\StockTrading\\backups\\stock.dump"
        ),
        "restore_note": (
            "웹 Restore는 제공하지 않습니다. "
            "pg_restore --clean --if-exists 를 CLI로 실행하세요."
        ),
        "checked_at": datetime.now(timezone.utc),
    }
