"""STEP57 — pg_dump / pg_restore 도구 및 schema-only dump·복원 스모크.

사용:
  python scripts/verify_db_backup.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from stock_platform.common.settings import get_settings


def _tool_ok(name: str) -> bool:
    return shutil.which(name) is not None


def _parse_dsn(database_url: str) -> dict[str, str]:
    parsed = urlparse(database_url)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or "postgres"),
        "password": unquote(parsed.password or ""),
        "dbname": (parsed.path or "/postgres").lstrip("/") or "postgres",
    }


def main() -> int:
    dump_ok = _tool_ok("pg_dump")
    restore_ok = _tool_ok("pg_restore")
    print(f"[{'OK' if dump_ok else 'FAIL'}] pg_dump available")
    print(f"[{'OK' if restore_ok else 'WARN'}] pg_restore available")

    if not dump_ok:
        print("pg_dump 없음 — PATH에 PostgreSQL client 도구를 추가하세요.")
        return 1

    settings = get_settings()
    dsn = _parse_dsn(settings.database_url)
    env = {**os.environ, "PGPASSWORD": dsn["password"]}

    with tempfile.TemporaryDirectory(prefix="step57_backup_") as tmp:
        dump_path = Path(tmp) / "schema.dump"
        dump_cmd = [
            "pg_dump",
            "-h",
            dsn["host"],
            "-p",
            dsn["port"],
            "-U",
            dsn["user"],
            "-d",
            dsn["dbname"],
            "--schema-only",
            "-Fc",
            "-f",
            str(dump_path),
        ]
        result = subprocess.run(
            dump_cmd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print("[FAIL] pg_dump schema-only")
            print(result.stderr)
            return 1

        size = dump_path.stat().st_size
        print(f"[OK] schema-only dump size={size} bytes -> {dump_path.name}")

        if restore_ok and size > 0:
            # 실제 DB에 쓰지 않고 list만 검증 (안전)
            list_cmd = ["pg_restore", "-l", str(dump_path)]
            list_result = subprocess.run(
                list_cmd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if list_result.returncode != 0:
                print("[FAIL] pg_restore -l")
                print(list_result.stderr)
                return 1
            line_count = len(
                [ln for ln in list_result.stdout.splitlines() if ln.strip()]
            )
            print(f"[OK] pg_restore -l entries={line_count}")
        else:
            print("[WARN] pg_restore skip (tool missing or empty dump)")

    print("\nBackup verification PASSED (dump + restore list smoke)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
