"""STEP 8-5-21 — Dump를 검증 DB로 restore 후 행수 비교 (운영 DB 비파괴).

필요 환경:
  PGPASSWORD_ADMIN — CREATE DATABASE 가능한 슈퍼유저 비밀번호
  또는 이미 존재하는 stock_platform_rc_verify / stock_platform_rc_restore
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


VERIFY_DB = os.environ.get("RC_RESTORE_DB", "stock_platform_rc_restore")
COMPARE_TABLES = [
    ("auth", "users"),
    ("trading", "user_broker_account"),
    ("trading", "paper_account"),
    ("trading", "trading_order"),
]


def _psql(env, host, port, user, database, sql: str) -> str:
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
            "-tAc",
            sql,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout or "psql failed")
    return (r.stdout or "").strip()


def main() -> int:
    from stock_platform.common.settings import get_settings

    settings = get_settings()
    parsed = urlparse(settings.database_url)
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    app_user = unquote(parsed.username or "postgres")
    app_password = unquote(parsed.password or "")
    source_db = (parsed.path or "/postgres").lstrip("/") or "postgres"

    backup_dir = Path(r"E:\StockTrading\backups")
    dumps = sorted(backup_dir.glob("stock_rc21_*.dump"))
    if not dumps:
        dumps = sorted(backup_dir.glob("stock_*.dump"))
    if not dumps:
        print("NO_DUMP_FOUND")
        return 2
    dump = dumps[-1]
    print(f"using_dump={dump.name}")

    admin_password = os.environ.get("PGPASSWORD_ADMIN", "").strip()
    admin_user = os.environ.get("PGUSER_ADMIN", "postgres")
    if not admin_password:
        print("PGPASSWORD_ADMIN_REQUIRED")
        return 4

    admin_env = {**os.environ, "PGPASSWORD": admin_password}
    # terminate + recreate
    try:
        _psql(
            admin_env,
            host,
            port,
            admin_user,
            "postgres",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{VERIFY_DB}' AND pid <> pg_backend_pid();",
        )
    except RuntimeError:
        pass
    _psql(
        admin_env,
        host,
        port,
        admin_user,
        "postgres",
        f"DROP DATABASE IF EXISTS {VERIFY_DB};",
    )
    _psql(
        admin_env,
        host,
        port,
        admin_user,
        "postgres",
        f"CREATE DATABASE {VERIFY_DB};",
    )

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
            VERIFY_DB,
            "--no-owner",
            "--no-acl",
            str(dump),
        ],
        env=admin_env,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    # pg_restore 는 warning 있어도 non-zero 일 수 있음 — 치명만 실패
    print("restore_exit", restore.returncode)

    app_env = {**os.environ, "PGPASSWORD": app_password}
    # alembic version on restore db via admin
    try:
        version = _psql(
            admin_env,
            host,
            port,
            admin_user,
            VERIFY_DB,
            "SELECT version_num FROM alembic_version LIMIT 1;",
        )
    except RuntimeError as exc:
        print("ALEMBIC_VERSION_FAIL", str(exc)[:200])
        version = ""
    print(f"restore_alembic={version}")

    source_env = {**os.environ, "PGPASSWORD": app_password}
    comparisons = []
    for schema, table in COMPARE_TABLES:
        sql = f"SELECT count(*) FROM {schema}.{table}"
        try:
            src = _psql(
                source_env, host, port, app_user, source_db, sql
            )
        except RuntimeError:
            src = "NA"
        try:
            dst = _psql(
                admin_env, host, port, admin_user, VERIFY_DB, sql
            )
        except RuntimeError:
            dst = "NA"
        comparisons.append(
            {
                "table": f"{schema}.{table}",
                "source": src,
                "restored": dst,
                "match": src == dst and src != "NA",
            }
        )
        print(f"compare {schema}.{table} src={src} dst={dst}")

    out = {
        "dump": dump.name,
        "verify_db": VERIFY_DB,
        "alembic": version,
        "comparisons": comparisons,
        "all_match": all(c["match"] for c in comparisons),
    }
    report = backup_dir / f"restore_verify_{dump.stem}.json"
    report.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("RESTORE_REPORT", report.name)
    print("RESTORE_OK" if out["all_match"] and version else "RESTORE_PARTIAL")
    return 0 if out["all_match"] and version else 5


if __name__ == "__main__":
    raise SystemExit(main())
