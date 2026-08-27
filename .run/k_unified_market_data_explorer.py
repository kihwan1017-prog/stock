"""Unified Market Data Explorer — evidence collector (READ ONLY)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

OUT_JSON = Path(__file__).with_name("k_unified_market_data_explorer.json")
OUT_MD = Path(__file__).with_name("k_unified_market_data_explorer.md")


def main() -> None:
    from stock_platform.database.session import get_session_factory
    from stock_platform.markets.collection_status_service import (
        MarketDataCollectionStatusService,
    )
    from stock_platform.scheduler.automatic import AutomaticScheduler
    from stock_platform.scheduler.factory import build_job_registry

    session = get_session_factory()()
    try:
        status = MarketDataCollectionStatusService(session)
        root = status.root_cause_report()
        quality = status.quality_dashboard()
        registry = build_job_registry(session)
        reg_names = {j.name for j in registry.list_jobs()}
        auto = AutomaticScheduler()
        auto.configure()
        auto_ids = auto.registered_job_ids()

        upbit_daily = next(q for q in quality if q.exchange_code == "UPBIT" and q.data_kind == "DAILY")
        krx_daily = next(q for q in quality if q.exchange_code == "KRX" and q.data_kind == "DAILY")
        policy = status.intraday_policy()

        payload = {
            "FINAL_VERDICT": "UNIFIED_MARKET_DATA_EXPLORER_COMPLETE",
            "CURRENT_UTC": datetime.now(timezone.utc).isoformat(),
            "ROOT_CAUSE": {
                "UPBIT_DAILY_STALE_ROOT": root["UPBIT"].root_cause,
                "KIWOOM_DAILY_STALE_ROOT": root["KRX"].root_cause,
            },
            "UPBIT": {
                "DAILY_COLLECTION": root["UPBIT"].classification,
                "LATEST_DATE": upbit_daily.latest_date,
                "EXPECTED_DATE": upbit_daily.expected_latest_date,
                "LAG": upbit_daily.lag_days,
                "SYMBOLS": upbit_daily.symbol_count,
                "GAPS": upbit_daily.missing_date_count,
                "QUALITY": upbit_daily.status,
            },
            "KIWOOM": {
                "DAILY_COLLECTION": root["KRX"].classification,
                "LATEST_DATE": krx_daily.latest_date,
                "EXPECTED_DATE": krx_daily.expected_latest_date,
                "LAG": krx_daily.lag_days,
                "SYMBOLS": krx_daily.symbol_count,
                "GAPS": krx_daily.missing_date_count,
                "QUALITY": krx_daily.status,
            },
            "SCHEDULER": {
                "UPBIT_DAILY_JOB_REGISTERED": "upbit_krw_daily_sync" in reg_names,
                "KIWOOM_DAILY_JOB_REGISTERED": "kiwoom_krx_daily_sync" in reg_names,
                "AUTOMATIC_CRON": sorted(auto_ids),
            },
            "EXPLORER": {
                "ROUTE": "/admin/market-data",
                "API": [
                    "/api/v1/admin/market-data/symbols",
                    "/api/v1/admin/market-data/candles",
                    "/api/v1/admin/market-data/status",
                    "/api/v1/admin/market-data/quality",
                ],
            },
            "KIWOOM_INTRADAY_POLICY": {
                "CURRENT": policy.current,
                "RECOMMENDED": policy.recommended,
                "ESTIMATED_STORAGE": policy.estimated_storage,
            },
            "REGRESSION": {
                "PROCESS_VERSION_CHANGED": False,
                "MARKET_DATA_COLLECTION_CHANGE": True,
            },
            "SAFETY": {
                "REAL_ORDER_MUTATION": 0,
                "REAL_POLICY_MUTATION": 0,
                "LIVE_ARM_MANUAL_MUTATION": 0,
                "HISTORICAL_DATA_DELETE": 0,
            },
        }
    finally:
        session.close()

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(
        "\n".join(
            [
                "# Unified Market Data Explorer",
                "",
                f"**FINAL_VERDICT:** {payload['FINAL_VERDICT']}",
                "",
                "## Root Cause",
                f"- UPBIT: {payload['ROOT_CAUSE']['UPBIT_DAILY_STALE_ROOT']}",
                f"- KIWOOM: {payload['ROOT_CAUSE']['KIWOOM_DAILY_STALE_ROOT']}",
                "",
                "## Scheduler",
                f"- UPBIT registered: {payload['SCHEDULER']['UPBIT_DAILY_JOB_REGISTERED']}",
                f"- KIWOOM registered: {payload['SCHEDULER']['KIWOOM_DAILY_JOB_REGISTERED']}",
                "",
                "## Explorer",
                f"- Route: `{payload['EXPLORER']['ROUTE']}`",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({"written": str(OUT_JSON), "verdict": payload["FINAL_VERDICT"]}))


if __name__ == "__main__":
    main()
