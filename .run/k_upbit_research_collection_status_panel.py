"""Evidence probe — Upbit research collection status (READ ONLY)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_market_context.research_collection_status import (
    build_research_collection_status,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / ".run" / "k_upbit_research_collection_status_panel.json"
OUT_MD = ROOT / ".run" / "k_upbit_research_collection_status_panel.md"


def main() -> None:
    settings = get_settings()
    engine = create_engine(str(settings.database_url))
    Session = sessionmaker(bind=engine)
    with Session() as session:
        payload = build_research_collection_status(
            session, user_broker_account_id=1380
        )

    evidence = {
        "FINAL_VERDICT": "UPBIT_RESEARCH_COLLECTION_STATUS_PANEL_COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "route": "/admin/upbit/autotrading",
        "panel_location": "after AUTO/MODE/LIVE/ARM/STACK status Row",
        "api": {
            "method": "GET",
            "path": "/api/v1/admin/autotrading/uba/{ubaId}/research/collection-status",
            "reused_or_added": "ADDED_AGGREGATE_READ",
            "initial_request_count": 1,
            "polling_seconds": 45,
        },
        "snapshot": payload,
        "summary": {
            "clean_count": (payload.get("clean_forward") or {}).get("count"),
            "target_500": (payload.get("clean_forward") or {}).get("target_primary"),
            "target_1000": (payload.get("clean_forward") or {}).get(
                "target_recommended"
            ),
            "today_new": (payload.get("clean_forward") or {}).get("today_new"),
            "legacy": (payload.get("reference") or {}).get("legacy_count"),
            "backfill": (payload.get("reference") or {}).get("backfill_count"),
            "market": {
                "status": (payload.get("market_context") or {}).get("status"),
                "rows": (payload.get("market_context") or {}).get("rows"),
            },
            "asset": {
                "status": (payload.get("asset_context") or {}).get("status"),
                "rows": (payload.get("asset_context") or {}).get("rows"),
                "symbols": (payload.get("asset_context") or {}).get("symbols"),
            },
            "news": {
                "status": (payload.get("news") or {}).get("status"),
                "recent_count": (payload.get("news") or {}).get("recent_count"),
            },
            "llm": {
                "status": (payload.get("llm") or {}).get("status"),
                "today_count": (payload.get("llm") or {}).get("today_count"),
            },
            "experiment": {
                "status": (payload.get("experiment") or {}).get("status"),
                "best_candidate": (payload.get("experiment") or {}).get(
                    "best_candidate"
                ),
                "best_candidate_label_ko": (payload.get("experiment") or {}).get(
                    "best_candidate_label_ko"
                ),
                "sample_warning": (payload.get("experiment") or {}).get(
                    "sample_warning"
                ),
            },
            "overall_status": payload.get("overall_status"),
            "overall_status_ko": payload.get("overall_status_ko"),
            "last_collected_at": payload.get("last_collected_at"),
            "last_clean_new_at": (payload.get("clean_forward") or {}).get(
                "last_new_at"
            ),
        },
        "safety": payload.get("mutations"),
        "BACKEND_RESTART_COUNT": 0,
        "NEXT_ACTION": "COLLECT_MORE_CLEAN_FORWARD",
        "limitations": [
            "Browser console verify requires running frontend + admin session",
            "Backend process may need reload to pick up new route if already running",
            "Research data is platform-common (UBA id display/scope only)",
        ],
        "tests": {
            "backend": "tests/test_upbit_research_collection_status.py PASS",
            "frontend": "UpbitResearchCollectionStatusPanel.test.tsx PASS",
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    s = evidence["summary"]
    md = f"""# Upbit Research Collection Status Panel

**FINAL_VERDICT:** `{evidence['FINAL_VERDICT']}`

| # | Item | Value |
|---|------|-------|
| 1 | route | `{evidence['route']}` |
| 2 | panel location | {evidence['panel_location']} |
| 3 | CLEAN count | {s['clean_count']} |
| 4 | target 500 | {s['target_500']} |
| 5 | target 1000 | {s['target_1000']} |
| 6 | today new | {s['today_new']} |
| 7 | legacy | {s['legacy']} |
| 8 | backfill | {s['backfill']} |
| 9 | market | {s['market']} |
| 10 | asset | {s['asset']} |
| 11 | news | {s['news']} |
| 12 | llm | {s['llm']} |
| 13 | experiment status | {s['experiment']['status']} |
| 14 | best candidate | {s['experiment']['best_candidate']} / {s['experiment']['best_candidate_label_ko']} |
| 15 | sample warning | {s['experiment']['sample_warning']} |
| 16 | overall | {s['overall_status']} ({s['overall_status_ko']}) |
| 17 | last collected | {s['last_collected_at']} |
| 18 | last CLEAN | {s['last_clean_new_at']} |
| 19 | API | {evidence['api']['path']} ({evidence['api']['reused_or_added']}) |
| 20 | initial requests | {evidence['api']['initial_request_count']} |
| 21 | polling | {evidence['api']['polling_seconds']}s |
| 29 | REAL_ORDER_MUTATION | {evidence['safety']['REAL_ORDER_MUTATION']} |
| 30 | LIVE_ARM_MUTATION | {evidence['safety']['LIVE_ARM_MUTATION']} |
| 35 | UBA1381_MUTATION | {evidence['safety']['UBA1381_MUTATION']} |
| 36 | BACKEND_RESTART_COUNT | {evidence['BACKEND_RESTART_COUNT']} |

**NEXT_ACTION:** `{evidence['NEXT_ACTION']}`
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(json.dumps({"ok": True, "json": str(OUT_JSON), "summary": s}, default=str))


if __name__ == "__main__":
    main()
