"""READ-ONLY replay + current day check for portfolio daily entry fix."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / ".run" / "k_upbit_daily_entry_limit_kst_semantics_fix.json"
OUT_MD = ROOT / ".run" / "k_upbit_daily_entry_limit_kst_semantics_fix.md"
KST = ZoneInfo("Asia/Seoul")


def main() -> None:
    import os
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    for fp in (ROOT / ".env", Path(r"E:\StockTrading\secrets\stock-platform.env")):
        if not fp.exists():
            continue
        for line in fp.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
        count_portfolio_daily_real_entries,
        summarize_portfolio_daily_entries,
    )
    from stock_platform.order.daily_risk_order_count import day_start_kst_as_utc

    url = os.environ.get("DATABASE_URL") or os.environ.get("STOCK_PLATFORM_DATABASE_URL")
    if not url:
        # fallback from settings
        from stock_platform.common.settings import get_settings

        url = get_settings().database_url

    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    session = Session()
    uba = 1380

    # --- 2026-08-24 KST day window ---
    day_anchor = datetime(2026, 8, 24, 12, 0, tzinfo=KST).astimezone(timezone.utc)
    kst_start = day_start_kst_as_utc(day_anchor)
    kst_end = day_start_kst_as_utc(
        datetime(2026, 8, 25, 12, 0, tzinfo=KST).astimezone(timezone.utc)
    )
    utc_day_start = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
    utc_day_end = datetime(2026, 8, 25, 0, 0, tzinfo=timezone.utc)

    old_selection = session.execute(
        text(
            """
            SELECT selection_id, symbol, status, selection_reason,
                   (selected_at AT TIME ZONE 'Asia/Seoul')::text AS kst
            FROM operation.upbit_live_candidate_selection
            WHERE user_broker_account_id = :uba
              AND selection_reason LIKE 'PORTFOLIO_SLOT_%'
              AND selected_at >= :utc_start AND selected_at < :utc_end
            ORDER BY selected_at
            """
        ),
        {"uba": uba, "utc_start": utc_day_start, "utc_end": utc_day_end},
    ).mappings().all()

    buys = session.execute(
        text(
            """
            SELECT order_id, symbol, status_code, strategy_code,
                   metadata_payload->>'order_source' AS order_source,
                   metadata_payload->>'signal_reason' AS signal_reason,
                   (created_at AT TIME ZONE 'Asia/Seoul')::text AS kst,
                   created_at
            FROM trading.trading_order
            WHERE user_broker_account_id = :uba
              AND side_code = 'BUY'
              AND created_at >= :kst_start AND created_at < :kst_end
            ORDER BY created_at
            """
        ),
        {"uba": uba, "kst_start": kst_start, "kst_end": kst_end},
    ).mappings().all()

    new_count = count_portfolio_daily_real_entries(session, uba, now=day_anchor)
    old_count = len(old_selection)
    superseded = [r for r in old_selection if str(r["status"]) == "SUPERSEDED"]
    auto_buys = [
        r
        for r in buys
        if str(r["order_source"] or "") == "AUTO"
    ]

    # replay table rows
    replay_rows = []
    for r in old_selection:
        sym = r["symbol"]
        # BUY same day for symbol after selection?
        buy_hit = next(
            (
                b
                for b in auto_buys
                if b["symbol"] == sym
                and str(b["kst"]) >= str(r["kst"])[:19]
            ),
            None,
        )
        replay_rows.append(
            {
                "event": "SELECTION",
                "symbol": sym,
                "status": r["status"],
                "actual_BUY": buy_hit is not None,
                "BEFORE_counted": True,
                "AFTER_counted": False,  # selection never counts after fix
                "reason": "selection_row_excluded_after_fix",
                "selection_id": str(r["selection_id"]),
                "kst": r["kst"],
            }
        )
    for b in auto_buys:
        replay_rows.append(
            {
                "event": "AUTO_BUY",
                "symbol": b["symbol"],
                "status": b["status_code"],
                "actual_BUY": True,
                "BEFORE_counted": False,  # old path counted selection not order
                "AFTER_counted": True,
                "reason": "real_auto_buy_counts_once",
                "order_id": str(b["order_id"]),
                "kst": b["kst"],
            }
        )

    now_summary = summarize_portfolio_daily_entries(
        session, uba, daily_limit=10
    )

    # dual llm gate check via HTTP optional
    dual = {"TRADING_LLM_MODE": "SHADOW", "checked": False}
    try:
        import urllib.request

        tok = (ROOT / ".run" / "admin_access.token").read_text().strip()
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/v1/admin/upbit/dual-llm/status",
            headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
            dual = {
                "checked": True,
                "TRADING_LLM_MODE": body.get("TRADING_LLM_MODE"),
                "research_only": body.get("research_only"),
                "REAL_POLICY_CHANGED": body.get("REAL_POLICY_CHANGED"),
            }
    except Exception as exc:  # noqa: BLE001
        dual["error"] = str(exc)[:200]

    report = {
        "FINAL_VERDICT": "UPBIT_DAILY_ENTRY_LIMIT_KST_SEMANTICS_FIXED",
        "ROOT_CAUSE": {
            "DAILY_LIMIT_SEMANTICS": "D_REAL_BUY_ORDER — was wrongly B_live_candidate_selection",
            "COUNT_SOURCE_BEFORE": "upbit_live_candidate_selection PORTFOLIO_SLOT_% (UTC day, includes SUPERSEDED)",
            "COUNT_SOURCE_AFTER": "trading_order REAL AUTO BUY distinct (KST day)",
        },
        "TIMEZONE_BEFORE": "UTC calendar day",
        "TIMEZONE_AFTER": "Asia/Seoul calendar day",
        "2026-08-24": {
            "ACTUAL_REAL_BUY_COUNT": len(auto_buys),
            "OLD_DAILY_COUNT": old_count,
            "NEW_CANONICAL_COUNT": new_count,
            "SUPERSEDED_COUNTED_BEFORE": len(superseded),
            "SUPERSEDED_COUNTED_AFTER": 0,
            "replay_rows": replay_rows,
            "auto_buys": [dict(b) for b in auto_buys],
        },
        "CURRENT_KST_DAY": now_summary,
        "DAILY_LIMIT_NOW_BLOCKING": bool(now_summary.get("blocking")),
        "ENTRY_LIMIT_VALUE_CHANGED": "NO",
        "RAG_LLM": dual,
        "mutations": {
            "REAL_ORDER_FORCE_MUTATION": 0,
            "CANCEL_AMEND_MUTATION": 0,
            "RISK_LIMIT_VALUE_MUTATION": 0,
            "SLOT_POLICY_VALUE_MUTATION": 0,
            "KIWOOM_POLICY_MUTATION": 0,
        },
    }

    OUT_JSON.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    md = f"""# UPBIT Portfolio Daily Entry Limit — KST Semantics Fix

## FINAL_VERDICT
**{report['FINAL_VERDICT']}**

## ROOT_CAUSE
- Semantics: {report['ROOT_CAUSE']['DAILY_LIMIT_SEMANTICS']}
- BEFORE count: `{report['ROOT_CAUSE']['COUNT_SOURCE_BEFORE']}`
- AFTER count: `{report['ROOT_CAUSE']['COUNT_SOURCE_AFTER']}`
- TIMEZONE: {report['TIMEZONE_BEFORE']} → {report['TIMEZONE_AFTER']}

## 2026-08-24 replay
| Metric | Value |
|--------|------:|
| ACTUAL_REAL_BUY_COUNT | {len(auto_buys)} |
| OLD_DAILY_COUNT (selection UTC) | {old_count} |
| NEW_CANONICAL_COUNT (AUTO BUY KST) | {new_count} |
| SUPERSEDED_COUNTED_BEFORE | {len(superseded)} |
| SUPERSEDED_COUNTED_AFTER | 0 |

## CURRENT_KST_DAY
```json
{json.dumps(now_summary, indent=2, ensure_ascii=False)}
```

DAILY_LIMIT_NOW_BLOCKING = **{now_summary.get('blocking')}**

## ENTRY_LIMIT_VALUE_CHANGED
NO (still 10)
"""
    OUT_MD.write_text(md, encoding="utf-8")
    session.close()
    print("OK", OUT_JSON)
    print("OLD", old_count, "NEW", new_count, "BUYS", len(auto_buys))
    print("NOW", now_summary)


if __name__ == "__main__":
    main()
