"""Git-tracked / 예시 파일 Secret 패턴 정적 검사 (원문 미출력)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 실제 값처럼 보이는 패턴 (placeholder 제외)
PATTERNS = [
    ("JWT_LIKE", re.compile(r"(?i)(jwt[_-]?secret)\s*[:=]\s*['\"][^'\"]{16,}['\"]")),
    ("PASSWORD_ASSIGN", re.compile(r"(?i)(password|secret_key|access_key)\s*[:=]\s*['\"][^'\"]{8,}['\"]")),
    ("TELEGRAM_TOKEN", re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")),
    ("AWS_KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
]

PLACEHOLDER = re.compile(
    r"(?i)(change-?me|your-|xxx|placeholder|example|dummy|test-secret|webhook-secret|local-dev)"
)

SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    ".next",
    "__pycache__",
    "backups",
}


def tracked_files() -> list[str]:
    r = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return [ln for ln in (r.stdout or "").splitlines() if ln.strip()]


def main() -> int:
    findings: list[dict] = []
    for rel in tracked_files():
        path = ROOT / rel
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".dump", ".zip", ".woff"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if PLACEHOLDER.search(line):
                continue
            for kind, pat in PATTERNS:
                if pat.search(line):
                    findings.append(
                        {
                            "file": rel,
                            "line": i,
                            "type": kind,
                            "git_tracked": True,
                        }
                    )
    print(f"FINDINGS={len(findings)}")
    for item in findings[:50]:
        print(
            f"{item['type']} {item['file']}:{item['line']} tracked={item['git_tracked']}"
        )
    # Critical = telegram token / aws in tracked non-example
    critical = [
        f
        for f in findings
        if f["type"] in {"TELEGRAM_TOKEN", "AWS_KEY"}
        and ".example" not in f["file"]
    ]
    print(f"CRITICAL={len(critical)}")
    return 0 if len(critical) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
