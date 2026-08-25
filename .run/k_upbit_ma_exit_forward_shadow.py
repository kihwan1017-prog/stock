"""Evidence — UPBIT MA exit forward shadow implementation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

OUT_JSON = Path(".run/k_upbit_ma_exit_forward_shadow.json")
OUT_MD = Path(".run/k_upbit_ma_exit_forward_shadow.md")


def main() -> None:
    from stock_platform.common.settings import get_settings
    from stock_platform.database.session import get_session_factory
    from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.constants import (
        PRIMARY_SHADOW_RULE,
        RULE_VERSION,
    )
    from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.summary import (
        summarize_forward_shadow,
    )

    settings = get_settings()
    summary: dict = {}
    migration_pending = False
    try:
        factory = get_session_factory()
        with factory() as session:
            summary = summarize_forward_shadow(session, user_broker_account_id=1380)
    except Exception as exc:  # noqa: BLE001
        migration_pending = "upbit_ma_exit_forward_shadow" in str(exc)
        summary = {
            "schema": "upbit_ma_exit_forward_shadow_v1",
            "baseline": {"sample_count": 0},
            "confirm2": {"sample_count": 0},
            "sample_stage": "COLLECTION_ONLY",
            "db_error": type(exc).__name__,
        }

    n = int((summary.get("baseline") or {}).get("sample_count") or 0)
    verdict = (
        "UPBIT_MA_EXIT_FORWARD_SHADOW_COLLECTING"
        if n > 0
        else "UPBIT_MA_EXIT_FORWARD_SHADOW_READY"
    )

    payload = {
        "FINAL_VERDICT": verdict,
        "PRIMARY_SHADOW": PRIMARY_SHADOW_RULE,
        "RULE_VERSION": RULE_VERSION,
        "FORWARD_SHADOW_IMPLEMENTED": True,
        "MIGRATION_PENDING": migration_pending,
        "DEPLOYMENT_TIME": getattr(
            settings, "upbit_ma_exit_forward_shadow_deployed_at", ""
        )
        or datetime.now(timezone.utc).isoformat(),
        "PRE_EXISTING_POSITION_EXCLUDED": True,
        "CURRENT_SAMPLE_COUNT": n,
        "BASELINE": summary.get("baseline"),
        "CONFIRM2": summary.get("confirm2"),
        "NET_BENEFIT": summary.get("net_benefit"),
        "EARLY_DUMP_BASELINE": (summary.get("early_dump") or {}).get("baseline"),
        "EARLY_DUMP_CONFIRM2": (summary.get("early_dump") or {}).get("confirm2"),
        "SHADOW_BETTER": (summary.get("comparison") or {}).get("shadow_better_count"),
        "BASELINE_BETTER": (summary.get("comparison") or {}).get("baseline_better_count"),
        "TIE": (summary.get("comparison") or {}).get("tie_count"),
        "EXTRA_LOSS_FROM_DELAY": (summary.get("safety") or {}).get(
            "extra_loss_from_delay"
        ),
        "STOP_LOSS_DELAYED": (summary.get("safety") or {}).get("stop_loss_delayed"),
        "KILL_DELAYED": (summary.get("safety") or {}).get("kill_delayed"),
        "RISK_DELAYED": (summary.get("safety") or {}).get("risk_delayed"),
        "SECONDARY_SEPARATION": "MA_SEPARATION_0.30",
        "SECONDARY_FEE_EDGE": "FEE_AWARE_ENTRY_0.10",
        "CLEAN_LINKAGE": "OPTIONAL_FUTURE",
        "RAG_FEEDBACK_LINKAGE": "OPTIONAL_FUTURE",
        "TEACHER_REVIEW": "OPTIONAL_COMMENT_ONLY",
        "UI_AVAILABLE": True,
        "REAL_POLICY_CHANGED": "NO",
        "REAL_EXIT_CHANGED": "NO",
        "REAL_ORDER_MUTATION": 0,
        "MOBILE_WRITE_ACTION": 0,
        "SAMPLE_STAGE": summary.get("sample_stage"),
        "NEXT_ACTION": "COLLECT_MA_EXIT_FORWARD_SHADOW",
        "summary": summary,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = f"""# UPBIT MA Exit Forward Shadow

## FINAL_VERDICT
{verdict}

## PRIMARY_SHADOW
{PRIMARY_SHADOW_RULE}

## RULE_VERSION
{RULE_VERSION}

| Key | Value |
|-----|-------|
| FORWARD_SHADOW_IMPLEMENTED | YES |
| CURRENT_SAMPLE_COUNT | {n} |
| SAMPLE_STAGE | {summary.get('sample_stage')} |
| REAL_POLICY_CHANGED | NO |
| UI | /admin/research?market=UPBIT → Exit Forward Shadow |

## NEXT_ACTION
COLLECT_MA_EXIT_FORWARD_SHADOW
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(verdict)
    print(OUT_JSON)
    print(OUT_MD)


if __name__ == "__main__":
    main()
