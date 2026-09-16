"""Run real-market LIVE shadow smoke (no order submit)."""

from __future__ import annotations

import asyncio
import json
import os
import sys

# ensure src on path when run as script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stock_platform.realtime.live_shadow_market_smoke import (
    run_kiwoom_real_market_shadow_smoke,
    run_upbit_real_market_shadow_smoke,
)


async def main() -> int:
    duration = float(os.environ.get("LIVE_SHADOW_SMOKE_SECONDS", "300"))
    print(json.dumps({"phase": "start", "duration_seconds": duration}))
    upbit = await run_upbit_real_market_shadow_smoke(
        duration_seconds=duration
    )
    print(json.dumps({"phase": "upbit", **upbit.to_public_dict()}, ensure_ascii=True))
    kiwoom = await run_kiwoom_real_market_shadow_smoke(
        duration_seconds=duration
    )
    print(json.dumps({"phase": "kiwoom", **kiwoom.to_public_dict()}, ensure_ascii=True))
    ok = (
        upbit.auth_ok
        and kiwoom.auth_ok
        and upbit.quotes_received > 0
        and kiwoom.quotes_received > 0
        and upbit.shadow_intents > 0
        and kiwoom.shadow_intents > 0
        and upbit.duplicate_intents == 0
        and kiwoom.duplicate_intents == 0
        and upbit.broker_submit_calls == 0
        and kiwoom.broker_submit_calls == 0
        and upbit.broker_cancel_calls == 0
        and kiwoom.broker_cancel_calls == 0
        and upbit.broker_replace_calls == 0
        and kiwoom.broker_replace_calls == 0
        and not upbit.secret_leaked
        and not kiwoom.secret_leaked
        and "BROKER_ORDER_ID_CREATED" not in upbit.errors
        and "BROKER_ORDER_ID_CREATED" not in kiwoom.errors
        and upbit.runtime_stopped
        and kiwoom.runtime_stopped
        and upbit.kill_blocked is not False
        and kiwoom.pause_blocked is not False
    )
    print(json.dumps({"phase": "summary", "pass": ok}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
