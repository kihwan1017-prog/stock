"""STEP 8-5-21 — Backup 생성 + checksum + 메타 (Secret 원문 미출력)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse


def main() -> int:
    from stock_platform.common.settings import get_settings

    settings = get_settings()
    parsed = urlparse(settings.database_url)
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    user = unquote(parsed.username or "postgres")
    password = unquote(parsed.password or "")
    dbname = (parsed.path or "/postgres").lstrip("/") or "postgres"

    backup_dir = Path(r"E:\StockTrading\backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_path = backup_dir / f"stock_rc21_{stamp}.dump"
    meta_path = backup_dir / f"stock_rc21_{stamp}.meta.json"

    env = {**dict(**__import__("os").environ), "PGPASSWORD": password}
    proc = subprocess.run(
        [
            "pg_dump",
            "-h",
            host,
            "-p",
            port,
            "-U",
            user,
            "-d",
            dbname,
            "-Fc",
            "-f",
            str(dump_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print("BACKUP_FAILED", proc.returncode)
        print((proc.stderr or "")[-400:])
        return proc.returncode

    size = dump_path.stat().st_size
    if size <= 0:
        print("BACKUP_EMPTY")
        return 3

    h = hashlib.sha256()
    with dump_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    checksum = h.hexdigest()

    # alembic head (운영 DB)
    cur = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        capture_output=True,
        text=True,
        check=False,
    )
    pg = subprocess.run(
        [
            "psql",
            "-h",
            host,
            "-p",
            port,
            "-U",
            user,
            "-d",
            dbname,
            "-tAc",
            "SHOW server_version;",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "db_name": dbname,
        "dump_file": dump_path.name,
        "size_bytes": size,
        "sha256": checksum,
        "alembic_current": (cur.stdout or "").strip(),
        "postgres_version": (pg.stdout or "").strip(),
        "exit_code": 0,
    }
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("BACKUP_OK")
    print(f"file={dump_path.name}")
    print(f"size_bytes={size}")
    print(f"sha256={checksum}")
    print(f"alembic={(cur.stdout or '').strip()}")
    print(f"pg={(pg.stdout or '').strip()}")
    print(f"meta={meta_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
