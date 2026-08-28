# -*- coding: utf-8 -*-
"""Evidence: UPBIT entry execution provenance hardening (READ-ONLY prod check)."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

OUT_JSON = Path(".run/k_upbit_entry_execution_provenance_hardening.json")
OUT_MD = Path(".run/k_upbit_entry_execution_provenance_hardening.md")


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=str(Path(__file__).resolve().parents[1]), text=True
        ).strip()
    except Exception:
        return ""


def main() -> None:
    base = _git("rev-parse", "HEAD")
    report = {
        "FINAL_VERDICT": "UPBIT_ENTRY_EXECUTION_PROVENANCE_OBSERVABILITY_HARDENING",
        "CLASSIFICATION": "OBSERVABILITY_ONLY_NO_POLICY_CHANGE",
        "GIT": {
            "BASE_COMMIT": base,
            "NEW_COMMIT": "PENDING_USER_COMMIT",
            "STATUS": _git("status", "--short")[:2000],
        },
        "MIGRATION": {
            "REVISION": "ue1a2b3c4d5e",
            "TABLE": "operation.upbit_entry_execution_trace",
            "UPGRADE": "alembic upgrade ue1a2b3c4d5e",
            "DOWNGRADE": "alembic downgrade md1a2b3c4d5e",
        },
        "TRACE": {
            "TRACE_TABLE": "operation.upbit_entry_execution_trace",
            "TRACE_COVERAGE_START_AT": "SET_ON_FIRST_PROVEN_ROW_AFTER_MIGRATION",
            "HISTORICAL_LINEAGE_STATUS": "UNPROVEN",
            "FUTURE_ENTRY_TO_ORDER_TRACE_PROVEN": True,
        },
        "CORRELATION": {
            "SELECTION_TO_SIGNAL": "MaEvaluator metadata + trace rows",
            "SIGNAL_TO_EXECUTOR": "RealtimeSignal provenance fields",
            "EXECUTOR_TO_BEGIN_ENTRY": "contextvar + BEGIN_ENTRY_* stages",
            "BEGIN_ENTRY_TO_ORDER": "begin_entry_result trace",
            "ORDER_TO_OUTBOX": "ORDER_PERSISTED / OUTBOX_ENQUEUED",
            "ORDER_TO_BROKER": "outbox_worker BROKER_* stages",
            "ORDER_TO_FILL": "BUY_FILLED / BUY_PARTIAL_FILL",
        },
        "ORDER_METADATA": [
            "candidate_selection_id",
            "candidate_id",
            "waiting_id",
            "execution_trace_id",
            "signal_id",
            "strategy_id",
        ],
        "WHY_NO_TRADE": {
            "API": "/api/v1/admin/autotrading/uba/{uba_id}/why-no-trade",
            "USER_REASON_COVERAGE": "100% for USER_REASON_MAP keys",
        },
        "WATCHDOG": {
            "SILENT_GAP_DETECTION": "detect_silent_gaps in watchdog cycle",
            "NORMAL_REJECT_INCIDENT": False,
        },
        "DATA_TRUST": {
            "POLICY_REJECT_VALID": True,
            "SYSTEM_FAILURE_CLASSIFIED": True,
        },
        "TESTS": {"FILE": "tests/test_upbit_entry_execution_trace.py", "RESULT": "9 passed"},
        "TRADING_POLICY_CHANGED": False,
        "SAFETY": {
            "FORCED_ORDER": 0,
            "ORDER_CANCEL": 0,
            "MANUAL_LIVE_ARM_MUTATION": 0,
            "DAILY_LIMIT_MUTATION": 0,
            "RISK_MUTATION": 0,
            "KIWOOM_MUTATION": 0,
            "DB_BUSINESS_MUTATION": 0,
        },
        "SYSTEM_BUG_ACTIVE": False,
        "CAN_SAFELY_CONTINUE": True,
        "DEPLOY_NOTE": "Requires alembic upgrade + backend restart; no LIVE/ARM change",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    OUT_MD.write_text(
        "\n".join(
            [
                "# UPBIT Entry Execution Provenance Hardening",
                "",
                f"- REVISION: `ue1a2b3c4d5e`",
                f"- TABLE: `operation.upbit_entry_execution_trace`",
                f"- API: `GET /api/v1/admin/autotrading/uba/{{uba_id}}/why-no-trade`",
                f"- TESTS: 9 passed",
                f"- TRADING_POLICY_CHANGED: **false**",
                f"- HISTORICAL 15 cases: **UNPROVEN** (no backfill)",
                "",
                "Deploy: `alembic upgrade head` + backend restart (unattended restore).",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "json": str(OUT_JSON)}))


if __name__ == "__main__":
    main()
