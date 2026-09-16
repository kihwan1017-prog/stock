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
