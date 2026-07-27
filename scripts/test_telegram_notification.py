#!/usr/bin/env python
"""Telegram 실제 발송 단독 점검 — 주문/Broker/Scheduler/DB mutation 없음.

Usage:
  python scripts/test_telegram_notification.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stock_platform.notification.telegram_standalone_test import (
    run_standalone_telegram_test,
)


if __name__ == "__main__":
    raise SystemExit(run_standalone_telegram_test())
