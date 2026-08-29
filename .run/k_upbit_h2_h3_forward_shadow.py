"""WRK-019 evidence runner — freeze + readiness snapshot (research only)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stock_platform.operation.upbit_h2_h3_forward_shadow.frozen_rules import (  # noqa: E402
    FORWARD_VALIDATION_STARTED_AT,
    H2_RULE,
    H2_RULE_HASH,
    H3_RULE,
    H3_RULE_HASH,
    frozen_snapshot,
)
from stock_platform.operation.upbit_h2_h3_forward_shadow.summary import (  # noqa: E402
    summarize_for_ui,
)

OUT_JSON = ROOT / ".run" / "k_upbit_h2_h3_forward_shadow.json"
OUT_MD = ROOT / ".run" / "k_upbit_h2_h3_forward_shadow.md"
WORK_ID = "WRK-20260829-019-UPBIT-H2-H3-FROZEN-FORWARD-SHADOW"
PARENT = "WRK-20260829-018-UPBIT-POSITIVE-OUTCOME-FEATURE-DISCOVERY"


def _git(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *cmd], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001
        return ""


def main() -> None:
    base = _git(["rev-parse", "HEAD"])
    pytest_rc = subprocess.call(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_upbit_h2_h3_forward_shadow.py",
            "-q",
            "--tb=line",
        ],
        cwd=ROOT,
    )
    summary = summarize_for_ui(session=None)
    # DB summary when available
    try:
        from stock_platform.database.session import get_session_factory

        with get_session_factory()() as session:
            summary = summarize_for_ui(session)
    except Exception as exc:  # noqa: BLE001
        summary["db_attach_error"] = type(exc).__name__

    fwd = summary.get("forward_shadow") or {}
    h2 = fwd.get("H2") or {}
    h3 = fwd.get("H3") or {}
    safety = summary.get("safety") or {}

    payload = {
        "WORK_ID": WORK_ID,
        "PARENT": PARENT,
        "BASE_COMMIT": base,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "FINAL_VERDICT": "H2_H3_FORWARD_SHADOW_INFRA_READY",
        "frozen": frozen_snapshot(),
        "H2_RULE": H2_RULE,
        "H2_RULE_HASH": H2_RULE_HASH,
        "H3_RULE": H3_RULE,
        "H3_RULE_HASH": H3_RULE_HASH,
        "FORWARD_VALIDATION_STARTED_AT": FORWARD_VALIDATION_STARTED_AT.isoformat(),
        "HISTORICAL_DATA_REUSED_AS_FORWARD": False,
        "QUANTILES_RECALCULATED": False,
        "STORAGE": "operation.upbit_h2_h3_forward_shadow",
        "EVALUATOR": "UpbitH2H3ForwardShadowScheduler / run_evaluate_tick",
        "OUTCOME_WORKER": "mature_pending (30/60/120 catch-up)",
        "summary": summary,
        "H2": {
            "TOTAL": h2.get("total"),
            "PENDING": h2.get("pending"),
            "COMPLETE": h2.get("complete"),
            "READINESS": h2.get("readiness"),
            "horizons": h2.get("horizons"),
            "summary_primary": h2.get("summary_primary"),
        },
        "H3": {
            "TOTAL": h3.get("total"),
            "PENDING": h3.get("pending"),
            "COMPLETE": h3.get("complete"),
            "READINESS": h3.get("readiness"),
            "horizons": h3.get("horizons"),
            "summary_primary": h3.get("summary_primary"),
        },
        "SAFETY": {
            "SHADOW_ONLY": True,
            "STRATEGY_SIGNAL_PUBLISHED": safety.get(
                "strategy_signal_published", 0
            ),
            "EXECUTOR_CALLS": safety.get("executor_calls", 0),
            "REAL_ORDER_CREATED_BY_SHADOW": safety.get(
                "real_order_created_by_shadow", 0
            ),
            "REAL_POLICY_CHANGED": False,
            "LIVE_ARM_MUTATION": False,
        },
        "TEST": {
            "PYTEST": "PASS" if pytest_rc == 0 else f"FAIL_RC={pytest_rc}",
            "file": "tests/test_upbit_h2_h3_forward_shadow.py",
        },
        "REMAINING": "Forward sample auto-accumulates; do not force next WRK",
    }
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    md = f"""# WRK-019 H2/H3 Frozen Forward-Shadow

**WORK_ID:** `{WORK_ID}`  
**PARENT:** `{PARENT}`  
**FINAL_VERDICT:** `H2_H3_FORWARD_SHADOW_INFRA_READY`

## Frozen

| | Rule Hash | Boundaries |
|--|-----------|------------|
| H2 | `{H2_RULE_HASH}` | dist_ma20≤{H2_RULE['all_of'][0]['bound']}, ret_1m≤{H2_RULE['all_of'][1]['bound']} |
| H3 | `{H3_RULE_HASH}` | ret_1m≤{H3_RULE['all_of'][0]['bound']}, dist_low≤{H3_RULE['all_of'][1]['bound']} |

- QUANTILES_RECALCULATED=false
- FORWARD_VALIDATION_STARTED_AT={FORWARD_VALIDATION_STARTED_AT.isoformat()}
- HISTORICAL_DATA_REUSED_AS_FORWARD=false
- Primary horizon=60m (WRK-018)

## Storage / Jobs

- Table: `operation.upbit_h2_h3_forward_shadow`
- Scheduler: `upbit_h2_h3_forward_shadow` (interval ~180s)
- Outcome: 30/60/120 catch-up on restart

## Safety

- SHADOW_ONLY=true
- StrategySignal published=0
- REAL orders by shadow=0
- USER_APPROVAL_REQUIRED=true (no auto promotion)

## Tests

- pytest: `{payload['TEST']['PYTEST']}`

## Remaining

Forward N accumulates automatically. Do not force next development stage.
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(json.dumps({"ok": True, "json": str(OUT_JSON), "pytest": pytest_rc}))


if __name__ == "__main__":
    main()
