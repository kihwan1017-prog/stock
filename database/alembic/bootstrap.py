"""Alembic bootstrap helpers — Version Table·플랫폼 스키마 선행 보장."""

from __future__ import annotations

# Version Table 위치 (env.py version_table_schema 와 동일)
ALEMBIC_VERSION_SCHEMA = "operation"

# 최초 revision(21ef733dc7ca)이 no-op 이므로 그린필드에서 선행 생성.
# STEP57(_SCHEMAS) + notification — 운영 DB 스키마 집합과 정합.
PLATFORM_SCHEMAS: tuple[str, ...] = (
    "auth",
    "market",
    "trading",
    "strategy",
    "operation",
    "news",
    "disclosure",
    "ai",
    "backtest",
    "broker",
    "common",
    "notification",
)


def ensure_operation_schema(connection) -> None:
    """하위 호환 별칭 — 플랫폼 스키마 전체 보장."""

    ensure_platform_schemas(connection)


def ensure_platform_schemas(connection) -> None:
    """
    version_table_schema=operation 및 조기 테이블 DDL용 스키마를
    Migration Context 전에 멱등 생성한다 (PostgreSQL only).
    """

    if connection.dialect.name != "postgresql":
        return

    from sqlalchemy import text

    try:
        for schema_name in PLATFORM_SCHEMAS:
            # 스키마명은 모듈 상수만 사용 (SQL injection 경로 없음)
            connection.execute(
                text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
            )
        connection.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            current_user = connection.execute(
                text("SELECT current_user")
            ).scalar()
        except Exception:  # noqa: BLE001
            current_user = "<unknown>"
        raise RuntimeError(
            "Failed to ensure Alembic bootstrap schemas "
            f"(required includes '{ALEMBIC_VERSION_SCHEMA}'). "
            f"current_user={current_user}. "
            "Grant CREATE privilege on the database "
            "(or use a role with CREATEDB/superuser for empty-DB bootstrap). "
            "Connection secrets are not logged."
        ) from exc


def emit_platform_schema_sql() -> list[str]:
    """Offline SQL용 CREATE SCHEMA 문 목록."""

    return [
        f"CREATE SCHEMA IF NOT EXISTS {schema_name}"
        for schema_name in PLATFORM_SCHEMAS
    ]
