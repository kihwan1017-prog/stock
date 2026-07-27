"""STEP 8-5-22 — 검증 DB 안전 생성/upgrade/restore (PGPASSWORD_ADMIN 필수).

금지: 운영 DB(stock_platform / prod / production / live) 삭제·초기화.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from psycopg import sql

VERIFY_PREFIXES = (
    "stock_platform_rc_verify_",
    "stock_platform_restore_verify_",
)
FORBIDDEN_NAMES = re.compile(
    r"(^stock_platform$|prod|production|live)", re.I
)
REPORT_DIR = Path(r"E:\StockTrading\backups\verification")
BACKUP_DIR = Path(r"E:\StockTrading\backups")

# 실제 ORM/DB 테이블은 auth.user (복수형 auth.users 아님)
COMPARE_TABLES: tuple[tuple[str, str], ...] = (
    ("auth", "user"),
    ("trading", "user_broker_account"),
    ("trading", "paper_account"),
    ("trading", "trading_order"),
    ("trading", "order_outbox"),
)

ERROR_TABLE_NOT_FOUND = "table_not_found"
ERROR_PERMISSION_DENIED = "permission_denied"
ERROR_QUERY_FAILED = "query_failed"
ERROR_CONNECTION_FAILED = "connection_failed"
ERROR_COUNT_MISMATCH = "count_mismatch"


def _fail(msg: str, code: int = 1) -> int:
    print(f"FAIL_CLOSED: {msg}")
    return code


def build_count_sql(schema_name: str, table_name: str) -> str:
    """스키마·테이블 Identifier를 안전하게 인용한 COUNT SQL."""

    return (
        sql.SQL("SELECT COUNT(*) FROM {}.{}")
        .format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
        )
        .as_string(None)
    )


def build_exists_sql(schema_name: str, table_name: str) -> str:
    """information_schema 기반 테이블 존재 여부 SQL (값 Literal)."""

    return (
        sql.SQL(
            "SELECT EXISTS ("
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = {} AND table_name = {}"
            ")"
        )
        .format(sql.Literal(schema_name), sql.Literal(table_name))
        .as_string(None)
    )


def classify_psql_failure(message: str) -> str:
    """psql/연결 오류를 진단 코드로 분류 (시크릿 미포함 메시지 기준)."""

    original = message or ""
    text = original.lower()
    if any(
        token in text
        for token in (
            "could not connect",
            "connection refused",
            "timeout expired",
            "server closed the connection",
            "연결할 수 없",
        )
    ):
        return ERROR_CONNECTION_FAILED
    if any(
        token in text
        for token in (
            "permission denied",
            "insufficient_privilege",
            "권한 없음",
            "허가 거부",
        )
    ):
        return ERROR_PERMISSION_DENIED
    if (
        "does not exist" in text
        or "undefinedtable" in text
        or "undefined_table" in text
        or "존재하지 않" in original
        or ("릴레이션" in original and "없" in original)
        or ("relation" in text and "exist" in text)
    ):
        return ERROR_TABLE_NOT_FOUND
    return ERROR_QUERY_FAILED


def _redact_secrets(message: str, *secrets: str) -> str:
    redacted = message or ""
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "***")
    # DSN 형태 마스킹
    redacted = re.sub(
        r"postgresql(\+psycopg)?://[^\s]+",
        "postgresql://***",
        redacted,
        flags=re.I,
    )
    return redacted


def _assert_safe_db_name(name: str) -> None:
    if not name or not any(name.startswith(p) for p in VERIFY_PREFIXES):
        raise PermissionError(
            f"DB name must start with verify prefix: {VERIFY_PREFIXES}"
        )
    if FORBIDDEN_NAMES.search(name) and not any(
        name.startswith(p) for p in VERIFY_PREFIXES
    ):
        raise PermissionError(f"Forbidden DB name: {name}")
    if name.lower() in {"stock_platform", "postgres", "template0", "template1"}:
        raise PermissionError(f"Forbidden DB name: {name}")


def _ops_db_name() -> str:
    from stock_platform.common.settings import get_settings

    return get_settings().db_name


def _conn_meta():
    from stock_platform.common.settings import get_settings

    s = get_settings()
    p = urlparse(s.database_url)
    return {
        "host": p.hostname or "localhost",
        "port": str(p.port or 5432),
        "app_user": unquote(p.username or ""),
        "app_password": unquote(p.password or ""),
        "ops_db": s.db_name,
    }


def _psql(env, host, port, user, database, query: str) -> str:
    r = subprocess.run(
        [
            "psql",
            "-h",
            host,
            "-p",
            port,
            "-U",
            user,
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-tAc",
            query,
        ],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=120,
    )
    if r.returncode != 0:
        raw = (r.stderr or r.stdout or "psql failed")[:400]
        secret = (env or {}).get("PGPASSWORD", "")
        raise RuntimeError(_redact_secrets(raw, secret))
    return (r.stdout or "").strip()


def _table_exists(
    runner: Callable[[str], str],
    schema_name: str,
    table_name: str,
) -> bool:
    raw = runner(build_exists_sql(schema_name, table_name)).lower()
    return raw in {"t", "true", "1", "yes"}


def _count_rows(
    runner: Callable[[str], str],
    schema_name: str,
    table_name: str,
) -> int:
    raw = runner(build_count_sql(schema_name, table_name))
    return int(raw)


def compare_table_row_counts(
    schema_name: str,
    table_name: str,
    source_runner: Callable[[str], str],
    restored_runner: Callable[[str], str],
) -> dict[str, Any]:
    """Source/Restore 행 수 비교. 오류 시 match=False + error 코드."""

    table_key = f"{schema_name}.{table_name}"
    result: dict[str, Any] = {
        "table": table_key,
        "source_exists": False,
        "restored_exists": False,
        "source_count": None,
        "restored_count": None,
        # 하위 호환 필드
        "source": None,
        "restored": None,
        "match": False,
        "error": None,
    }

    try:
        source_exists = _table_exists(source_runner, schema_name, table_name)
    except RuntimeError as exc:
        result["error"] = classify_psql_failure(str(exc))
        return result

    result["source_exists"] = source_exists

    try:
        restored_exists = _table_exists(
            restored_runner, schema_name, table_name
        )
    except RuntimeError as exc:
        result["error"] = classify_psql_failure(str(exc))
        return result

    result["restored_exists"] = restored_exists

    if not source_exists or not restored_exists:
        result["error"] = ERROR_TABLE_NOT_FOUND
        return result

    try:
        source_count = _count_rows(source_runner, schema_name, table_name)
    except RuntimeError as exc:
        result["error"] = classify_psql_failure(str(exc))
        return result

    try:
        restored_count = _count_rows(restored_runner, schema_name, table_name)
    except RuntimeError as exc:
        result["error"] = classify_psql_failure(str(exc))
        return result

    result["source_count"] = source_count
    result["restored_count"] = restored_count
    result["source"] = str(source_count)
    result["restored"] = str(restored_count)
    if source_count != restored_count:
        result["error"] = ERROR_COUNT_MISMATCH
        result["match"] = False
        return result

    result["match"] = True
    result["error"] = None
    return result


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_empty_upgrade() -> int:
    admin_pw = (os.environ.get("PGPASSWORD_ADMIN") or "").strip()
    if not admin_pw:
        return _fail("PGPASSWORD_ADMIN required", 4)
    admin_user = os.environ.get("PGUSER_ADMIN", "postgres")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_name = os.environ.get(
        "RC_VERIFY_DB_NAME", f"stock_platform_rc_verify_{stamp}"
    )
    try:
        _assert_safe_db_name(db_name)
    except PermissionError as exc:
        return _fail(str(exc), 5)

    meta = _conn_meta()
    if db_name == meta["ops_db"]:
        return _fail("verify DB equals ops DB", 5)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    admin_env = {**os.environ, "PGPASSWORD": admin_pw}
    host, port = meta["host"], meta["port"]

    # createdb privilege check
    flags = _psql(
        admin_env,
        host,
        port,
        admin_user,
        "postgres",
        "SELECT rolsuper, rolcreatedb FROM pg_roles WHERE rolname = current_user;",
    )
    print(f"admin_role_flags={flags}")
    if flags.split("|")[0] not in {"t", "true"} and flags.split("|")[-1] not in {
        "t",
        "true",
    }:
        return _fail("admin lacks CREATEDB/superuser", 6)

    try:
        _psql(
            admin_env,
            host,
            port,
            admin_user,
            "postgres",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{db_name}' AND pid <> pg_backend_pid();",
        )
    except RuntimeError:
        pass
    _psql(
        admin_env,
        host,
        port,
        admin_user,
        "postgres",
        f"DROP DATABASE IF EXISTS {db_name};",
    )
    _psql(
        admin_env,
        host,
        port,
        admin_user,
        "postgres",
        f"CREATE DATABASE {db_name};",
    )
    print(f"created_db={db_name}")

    alembic_env = {
        **os.environ,
        "DB_NAME": db_name,
        "DB_HOST": host,
        "DB_PORT": port,
        "DB_USER": meta["app_user"],
        "DB_PASSWORD": meta["app_password"],
        "PGPASSWORD": meta["app_password"],
    }
    # grant connect/create to app user
    try:
        _psql(
            admin_env,
            host,
            port,
            admin_user,
            "postgres",
            f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {meta['app_user']};",
        )
    except RuntimeError as exc:
        print("grant_warn", str(exc)[:120])

    up = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=alembic_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    print((up.stderr or "")[-500:])
    if up.returncode != 0:
        return _fail("alembic upgrade failed", up.returncode)

    cur = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        env=alembic_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    current = (cur.stdout or "").strip()
    print(f"alembic_current={current}")

    schemas = _psql(
        admin_env,
        host,
        port,
        admin_user,
        db_name,
        "SELECT string_agg(schema_name, ',' ORDER BY schema_name) "
        "FROM information_schema.schemata "
        "WHERE schema_name IN "
        "('common','market','trading','news','disclosure','ai','operation','public');",
    )
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "db_name": db_name,
        "alembic_current": current,
        "schemas": schemas,
        "ops_db": meta["ops_db"],
        "ok": (
            "o4e5f6a7b8c9" in current
            or "n3d4e5f6a7b8" in current
            or "m0a1b2c3d4e5" in current
            or "l9c0d1e2f3a4" in current
            or "k8b9c0d1e2f3" in current
            or "j3d4e5f6a7b8" in current
            or "head" in current.lower()
        ),
    }
    # head may advance with later STEPs
    out = REPORT_DIR / "rc22_empty_db_upgrade_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("EMPTY_DB_OK" if report["ok"] else "EMPTY_DB_PARTIAL")
    print(f"report={out}")
    return (
        0
        if (
            "o4e5f6a7b8c9" in current
            or "n3d4e5f6a7b8" in current
            or "m0a1b2c3d4e5" in current
            or "l9c0d1e2f3a4" in current
            or "k8b9c0d1e2f3" in current
            or "j3d4e5f6a7b8" in current
            or "i2c3d4e5f6a7" in current
        )
        else 7
    )

def cmd_restore() -> int:
    admin_pw = (os.environ.get("PGPASSWORD_ADMIN") or "").strip()
    if not admin_pw:
        return _fail("PGPASSWORD_ADMIN required", 4)
    admin_user = os.environ.get("PGUSER_ADMIN", "postgres")
    expected = (
        os.environ.get("RC_BACKUP_SHA256")
        or "739271404934a5eac23feb0238c48e6d45a8e01d52ab2b57b92d701efdbe9674"
    )
    dump_name = os.environ.get(
        "RC_BACKUP_FILE", "stock_rc21_20260726_092023.dump"
    )
    dump = BACKUP_DIR / dump_name
    if not dump.exists():
        return _fail(f"dump missing: {dump_name}", 2)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    checksum = sha256_file(dump)
    (REPORT_DIR / "rc22_checksum_report.txt").write_text(
        f"file={dump.name}\nsha256={checksum}\nexpected={expected}\n"
        f"match={checksum == expected}\n",
        encoding="utf-8",
    )
    if checksum != expected:
        return _fail("checksum mismatch — restore aborted", 3)
    print("checksum_ok")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_name = os.environ.get(
        "RC_RESTORE_DB_NAME", f"stock_platform_restore_verify_{stamp}"
    )
    try:
        _assert_safe_db_name(db_name)
    except PermissionError as exc:
        return _fail(str(exc), 5)

    meta = _conn_meta()
    if db_name == meta["ops_db"]:
        return _fail("restore DB equals ops DB", 5)

    admin_env = {**os.environ, "PGPASSWORD": admin_pw}
    host, port = meta["host"], meta["port"]
    try:
        _psql(
            admin_env,
            host,
            port,
            admin_user,
            "postgres",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{db_name}' AND pid <> pg_backend_pid();",
        )
    except RuntimeError:
        pass
    _psql(
        admin_env,
        host,
        port,
        admin_user,
        "postgres",
        f"DROP DATABASE IF EXISTS {db_name};",
    )
    _psql(
        admin_env,
        host,
        port,
        admin_user,
        "postgres",
        f"CREATE DATABASE {db_name};",
    )

    log_path = REPORT_DIR / "rc22_restore_pg_restore.log"
    restore = subprocess.run(
        [
            "pg_restore",
            "-h",
            host,
            "-p",
            port,
            "-U",
            admin_user,
            "-d",
            db_name,
            "--no-owner",
            "--no-acl",
            str(dump),
        ],
        env=admin_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    log_path.write_text(
        (restore.stdout or "") + "\n" + (restore.stderr or ""),
        encoding="utf-8",
    )
    print(f"pg_restore_exit={restore.returncode}")

    try:
        version = _psql(
            admin_env,
            host,
            port,
            admin_user,
            db_name,
            'SELECT version_num FROM "operation"."alembic_version" LIMIT 1;',
        )
    except RuntimeError:
        try:
            version = _psql(
                admin_env,
                host,
                port,
                admin_user,
                db_name,
                "SELECT version_num FROM alembic_version LIMIT 1;",
            )
        except RuntimeError:
            version = ""

    source_env = {**os.environ, "PGPASSWORD": meta["app_password"]}

    def source_runner(query: str) -> str:
        return _psql(
            source_env,
            host,
            port,
            meta["app_user"],
            meta["ops_db"],
            query,
        )

    def restored_runner(query: str) -> str:
        return _psql(admin_env, host, port, admin_user, db_name, query)

    comparisons: list[dict[str, Any]] = []
    for schema_name, table_name in COMPARE_TABLES:
        # 잘못된 복수형 테이블명 방어
        if schema_name == "auth" and table_name == "users":
            return _fail(
                "invalid compare target auth.users "
                "(use auth.user)",
                8,
            )
        item = compare_table_row_counts(
            schema_name,
            table_name,
            source_runner,
            restored_runner,
        )
        comparisons.append(item)
        src = item["source_count"] if item["source_count"] is not None else "NA"
        dst = (
            item["restored_count"]
            if item["restored_count"] is not None
            else "NA"
        )
        print(f"compare {schema_name}.{table_name} src={src} dst={dst}")
        if item["error"]:
            print(f"compare_error {schema_name}.{table_name}={item['error']}")

    # upgrade restore DB to head if behind
    alembic_env = {
        **os.environ,
        "DB_NAME": db_name,
        "DB_HOST": host,
        "DB_PORT": port,
        "DB_USER": meta["app_user"],
        "DB_PASSWORD": meta["app_password"],
    }
    up = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=alembic_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    cur = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        env=alembic_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    all_match = all(c.get("match") is True for c in comparisons)
    first_error = next(
        (c["error"] for c in comparisons if c.get("error")), None
    )
    report = {
        "db_name": db_name,
        "dump": dump.name,
        "checksum_ok": True,
        "restore_exit": restore.returncode,
        "alembic_at_restore": version,
        "alembic_after_upgrade": (cur.stdout or "").strip(),
        "upgrade_exit": up.returncode,
        "comparisons": comparisons,
        "all_match": all_match,
        "first_error": first_error,
    }
    (REPORT_DIR / "rc22_restore_verification_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (REPORT_DIR / "rc22_row_count_comparison.json").write_text(
        json.dumps(comparisons, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not all_match:
        detail = first_error or "row count mismatch"
        print("RESTORE_PARTIAL")
        return _fail(f"restore compare failed: {detail}", 8)
    print("RESTORE_OK")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: rc22_db_verify.py [empty-upgrade|restore]")
        return 2
    cmd = sys.argv[1]
    if cmd == "empty-upgrade":
        return cmd_empty_upgrade()
    if cmd == "restore":
        return cmd_restore()
    return _fail(f"unknown command {cmd}", 2)


if __name__ == "__main__":
    raise SystemExit(main())
