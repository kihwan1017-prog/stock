"""Run LIVE pre-order dry-run smoke (no broker submit)."""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stock_platform.realtime.live_pre_order_dry_run_smoke import (
    run_kiwoom_dry_run_smoke,
    run_upbit_dry_run_smoke,
)


async def main() -> int:
    duration = float(os.environ.get("LIVE_DRY_RUN_SMOKE_SECONDS", "90"))
    print(json.dumps({"phase": "start", "duration_seconds": duration}))
    upbit = await run_upbit_dry_run_smoke(duration_seconds=duration)
    print(json.dumps({"phase": "upbit", **upbit.to_public_dict()}, ensure_ascii=True))
    kiwoom = await run_kiwoom_dry_run_smoke(duration_seconds=duration)
    print(json.dumps({"phase": "kiwoom", **kiwoom.to_public_dict()}, ensure_ascii=True))

    krx_closed = not bool(kiwoom.detail.get("krx_live_allowed"))
    kiwoom_ok = (
        kiwoom.quotes_received > 0
        and kiwoom.broker_submit_calls == 0
        and not kiwoom.secret_leaked
        and kiwoom.runtime_stopped
        and kiwoom.pause_blocked is not False
        and bool(kiwoom.detail.get("pause_via_orm"))
        and (
            (krx_closed and kiwoom.shadow_intents == 0)
            or ((not krx_closed) and kiwoom.auth_ok and kiwoom.shadow_intents > 0)
        )
        and (
            kiwoom.auth_ok
            or (krx_closed and any("KIWOOM_AUTH" in e for e in kiwoom.errors))
        )
    )
    upbit_ok = (
        upbit.auth_ok
        and upbit.quotes_received > 0
        and upbit.shadow_intents > 0
        and upbit.duplicate_intents == 0
        and upbit.broker_submit_calls == 0
        and not upbit.secret_leaked
        and upbit.kill_blocked is not False
        and upbit.runtime_stopped
        and upbit.detail.get("pre_submit_ok") is not False
    )
    ok = upbit_ok and kiwoom_ok
    print(
        json.dumps(
            {
                "phase": "summary",
                "pass": ok,
                "upbit_ok": upbit_ok,
                "kiwoom_ok": kiwoom_ok,
                "krx_closed": krx_closed,
            }
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
