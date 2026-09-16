"""관찰 루프. crash해도 Trading AUTO/LIVE에 연결되지 않는다."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stock_platform.operation.paper_shadow_observer.dry_pipeline import observe_one
from stock_platform.operation.paper_shadow_observer.guard import assert_observation_only
from stock_platform.operation.paper_shadow_observer.public_market import (
    fetch_krw_markets,
    fetch_public_tickers,
)
from stock_platform.operation.paper_shadow_observer.store import (
    DEFAULT_DIR,
    append_jsonl,
    write_status,
)
from stock_platform.operation.upbit_market_context.analysis_llm_service import (
    run_analysis_llm,
)
from stock_platform.operation.upbit_market_context.schemas import LlmContextInput
from stock_platform.operation.upbit_market_context.trading_llm_shadow import (
    run_trading_llm_shadow,
)

PID_FILE = Path(r"D:\Projects\stock-platform\.run\shadow-observer.pid")


def _analysis(inp: LlmContextInput, symbol: str) -> dict[str, Any]:
    return run_analysis_llm(inp, symbol=symbol, force_refresh=True)


def _trading(inp: LlmContextInput, analysis: dict[str, Any]) -> dict[str, Any]:
    return run_trading_llm_shadow(
        inp,
        analysis_summary=analysis,
        heuristic=None,
        rag_examples=[],
    )


def _pick_diverse(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        try:
            change = float(row.get("signed_change_rate") or 0)
        except (TypeError, ValueError):
            continue
        scored.append((change, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) <= limit:
        return [item[1] for item in scored]
    step = max(1, len(scored) // limit)
    picked = [scored[index][1] for index in range(0, len(scored), step)]
    return picked[:limit]


def run_once(*, limit: int = 36) -> list[dict[str, Any]]:
    assert_observation_only()
    markets = fetch_krw_markets()
    tickers = fetch_public_tickers(markets[:100])
    selected = _pick_diverse(tickers, limit)
    records: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        record = observe_one(row, run_analysis=_analysis, run_trading=_trading)
        append_jsonl(record)
        records.append(record)
        write_status({
            "state": "RUNNING",
            "last_observation": record.get("timestamp"),
            "last_success": record.get("timestamp") if record.get("trading_ok") else None,
            "last_error": record.get("error"),
            "model": record.get("model"),
            "endpoint": os.environ.get("OLLAMA_BASE_URL") or "http://192.168.1.10:11434",
            "observation_count": index,
            "symbol": record.get("symbol"),
            "order_created": 0,
            "outbox_created": 0,
        })
        print(
            f"OBS {index}/{len(selected)} {record.get('symbol')} "
            f"{record.get('trading_recommendation')} gate={record.get('ai_gate', {}).get('decision')} "
            f"risk={record.get('risk_dry', {}).get('decision')}",
            flush=True,
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="PAPER SHADOW observation-only runner")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=36)
    parser.add_argument("--loop-seconds", type=int, default=0, help="0이면 1회")
    args = parser.parse_args()
    os.environ.setdefault("STOCK_PLATFORM_ENV_FILE", r"E:\StockTrading\secrets\stock-platform.env")
    os.environ["SHADOW_OBSERVATION_ONLY"] = "true"
    DEFAULT_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    try:
        if args.once or args.loop_seconds <= 0:
            records = run_once(limit=args.limit)
            write_status({
                "state": "STOPPED",
                "last_observation": records[-1]["timestamp"] if records else None,
                "last_success": records[-1]["timestamp"] if records and records[-1].get("trading_ok") else None,
                "last_error": None,
                "model": records[-1].get("model") if records else None,
                "endpoint": "http://192.168.1.10:11434",
                "observation_count": len(records),
                "stopped_at": datetime.now(timezone.utc).isoformat(),
            })
            print(json.dumps({"observations": len(records), "order_created": 0}, ensure_ascii=False))
            return
        total = 0
        while True:
            batch = run_once(limit=args.limit)
            total += len(batch)
            write_status({
                "state": "RUNNING",
                "last_observation": batch[-1]["timestamp"] if batch else None,
                "observation_count": total,
                "model": "qwen3.5:4b",
                "endpoint": "http://192.168.1.10:11434",
            })
            time.sleep(max(30, args.loop_seconds))
    finally:
        if PID_FILE.is_file():
            PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
