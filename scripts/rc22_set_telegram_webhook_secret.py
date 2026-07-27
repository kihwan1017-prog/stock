"""STEP 8-5-22 — TELEGRAM_WEBHOOK_SECRET 생성·운영 env 반영 (원문 미출력)."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path

ENV_PATH = Path(r"E:\StockTrading\secrets\stock-platform.env")
BACKUP_DIR = Path(r"E:\StockTrading\secrets\backups")


def main() -> int:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = BACKUP_DIR / f"stock-platform.env.bak_{stamp}"
    text = ENV_PATH.read_text(encoding="utf-8", errors="replace")
    bak.write_text(text, encoding="utf-8")

    lines = text.splitlines()
    found = False
    current = ""
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if s.startswith("TELEGRAM_WEBHOOK_SECRET="):
            found = True
            current = s.split("=", 1)[1].strip()
            if current:
                out.append(line)
                print("ALREADY_SET")
                print(f"length={len(current)}")
                print(f"masked={current[:2]}***{current[-2:] if len(current)>4 else ''}")
                print(f"backup={bak.name}")
                return 0
            new_secret = secrets.token_urlsafe(32)
            out.append(f"TELEGRAM_WEBHOOK_SECRET={new_secret}")
            length = len(new_secret)
            masked = f"{new_secret[:2]}***{new_secret[-2:]}"
        else:
            out.append(line)

    if not found:
        new_secret = secrets.token_urlsafe(32)
        out.append("")
        out.append("# STEP 8-5-22 Telegram webhook secret")
        out.append(f"TELEGRAM_WEBHOOK_SECRET={new_secret}")
        length = len(new_secret)
        masked = f"{new_secret[:2]}***{new_secret[-2:]}"

    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    # 재확인 (원문 미출력)
    vals = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("TELEGRAM_WEBHOOK_SECRET="):
            vals["TELEGRAM_WEBHOOK_SECRET"] = s.split("=", 1)[1].strip()
    secret = vals.get("TELEGRAM_WEBHOOK_SECRET", "")
    print("SET_OK")
    print(f"length={len(secret)}")
    print(f"masked={secret[:2]}***{secret[-2:] if len(secret)>4 else ''}")
    print(f"changed_at={datetime.now(timezone.utc).isoformat()}")
    print(f"backup={bak.name}")
    return 0 if secret else 1


if __name__ == "__main__":
    raise SystemExit(main())
