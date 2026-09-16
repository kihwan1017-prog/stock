"""관찰 기록 JSONL. secret 키를 저장하지 않는다."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SECRET_KEY_FRAGMENTS = (
    "secret",
    "password",
    "token",
    "apikey",
    "api_key",
    "vault",
    "credential",
    "authorization",
)

DEFAULT_DIR = Path(r"D:\Projects\stock-platform\.run\paper-shadow-observation")
MAX_JSONL_BYTES = 20 * 1024 * 1024
JSONL_KEEP = 3


def rotate_jsonl_if_needed(
    path: Path | None = None,
    *,
    max_bytes: int = MAX_JSONL_BYTES,
    keep: int = JSONL_KEEP,
) -> bool:
    """JSONL이 max_bytes를 넘으면 .1 .2 로 회전. T7/운영 DB는 건드리지 않음."""

    target = path or (DEFAULT_DIR / "observations.jsonl")
    if not target.is_file():
        return False
    try:
        size = target.stat().st_size
    except OSError:
        return False
    if size < max_bytes:
        return False
    for index in range(keep, 0, -1):
        older = target.with_name(f"{target.name}.{index}")
        newer = target.with_name(f"{target.name}.{index - 1}") if index > 1 else target
        if index == keep and older.is_file():
            older.unlink(missing_ok=True)
        if newer.is_file():
            newer.replace(older)
    return True


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """민감 키는 값 대신 REDACTED."""

    clean: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        if any(fragment in lowered for fragment in SECRET_KEY_FRAGMENTS):
            clean[key] = "REDACTED"
            continue
        if isinstance(value, dict):
            clean[key] = redact(value)
        else:
            clean[key] = value
    return clean


def append_jsonl(record: dict[str, Any], *, path: Path | None = None) -> Path:
    target_dir = DEFAULT_DIR if path is None else path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target = path or (DEFAULT_DIR / "observations.jsonl")
    rotate_jsonl_if_needed(target)
    line = json.dumps(redact(record), ensure_ascii=False, default=str)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return target


def write_status(status: dict[str, Any], *, path: Path | None = None) -> Path:
    target = path or (DEFAULT_DIR / "status.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(redact(status), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return target


def read_status(*, path: Path | None = None) -> dict[str, Any]:
    target = path or (DEFAULT_DIR / "status.json")
    if not target.is_file():
        return {"state": "STOPPED", "reason": "NO_STATUS_FILE"}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"state": "UNKNOWN", "reason": "STATUS_UNREADABLE"}
    return raw if isinstance(raw, dict) else {"state": "UNKNOWN"}
