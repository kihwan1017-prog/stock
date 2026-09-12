"""Kiwoom-only real-quote dry-run smoke (no order submit)."""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stock_platform.realtime.live_pre_order_dry_run_smoke import (
    run_kiwoom_dry_run_smoke,
)


async def main() -> int:
    duration = float(os.environ.get("LIVE_DRY_RUN_SMOKE_SECONDS", "90"))
    print(json.dumps({"phase": "start", "duration_seconds": duration}))
    kiwoom = await run_kiwoom_dry_run_smoke(duration_seconds=duration)
    print(json.dumps({"phase": "kiwoom", **kiwoom.to_public_dict()}, ensure_ascii=True))
    krx_open = bool(kiwoom.detail.get("krx_live_allowed"))
    real_quotes = kiwoom.auth_ok and kiwoom.quotes_received > 0 and (
        kiwoom.detail.get("quote_source") != "SYNTHETIC_CLOSED_MARKET"
    )
    ok = (
        kiwoom.auth_ok
        and real_quotes
        and kiwoom.broker_submit_calls == 0
        and kiwoom.broker_cancel_calls == 0
        and kiwoom.broker_replace_calls == 0
        and not kiwoom.secret_leaked
        and kiwoom.runtime_stopped
        and "BROKER_ORDER_ID_CREATED" not in kiwoom.errors
        and (
            (krx_open and kiwoom.shadow_intents > 0)
            or ((not krx_open) and kiwoom.shadow_intents == 0)
        )
        and kiwoom.pause_blocked is not False
    )
    print(
        json.dumps(
            {
                "phase": "summary",
                "pass": ok,
                "krx_open": krx_open,
                "real_quotes": real_quotes,
                "auth_ok": kiwoom.auth_ok,
                "quotes": kiwoom.quotes_received,
                "candidates": kiwoom.shadow_intents,
                "submit": kiwoom.broker_submit_calls,
            }
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
