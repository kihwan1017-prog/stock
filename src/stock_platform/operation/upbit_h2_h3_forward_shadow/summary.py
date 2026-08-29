"""Admin/research summary for H2/H3 forward shadow + WRK-018 historical reference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.operation.upbit_h2_h3_forward_shadow.frozen_rules import (
    FORWARD_VALIDATION_STARTED_AT,
    H2_LEGACY_NAME,
    H2_NAME,
    H2_RULE,
    H2_RULE_HASH,
    H3_LEGACY_NAME,
    H3_NAME,
    H3_RULE,
    H3_RULE_HASH,
    PRIMARY_HORIZON_MIN,
    RULE_VERSION,
)
from stock_platform.operation.upbit_h2_h3_forward_shadow.scheduler import (
    runtime_status,
)
from stock_platform.operation.upbit_h2_h3_forward_shadow.service import (
    readiness_for,
)

_EVIDENCE = Path(".run/k_upbit_positive_outcome_feature_discovery.json")


def _historical_ref() -> dict[str, Any]:
    if not _EVIDENCE.is_file():
        return {"ok": False, "message": "WRK-018 evidence missing"}
    raw = json.loads(_EVIDENCE.read_text(encoding="utf-8"))
    val = raw.get("VALIDATION") or {}
    test = raw.get("TEST") or {}

    def _pack(legacy: str, label: str) -> dict[str, Any]:
        v = val.get(legacy) or {}
        t = test.get(legacy) or {}
        return {
            "strategy": label,
            "legacy_name": legacy,
            "source": "HISTORICAL",
            "validation": {
                "n": v.get("n"),
                "pf": v.get("pf"),
                "total_net": v.get("total_net"),
            },
            "test": {
                "n": t.get("n"),
                "pf": t.get("pf"),
                "total_net": t.get("total_net"),
            },
        }

    return {
        "ok": True,
        "source": "HISTORICAL",
        "wrk018": True,
        "H2": _pack(H2_LEGACY_NAME, H2_NAME),
        "H3": _pack(H3_LEGACY_NAME, H3_NAME),
        "note": "Historical must NOT be merged into forward promotion sample",
    }


def summarize_for_ui(session: Session | None = None) -> dict[str, Any]:
    """Forward shadow status + historical reference (separated)."""

    historical = _historical_ref()
    forward: dict[str, Any] = {
        "source": "FORWARD_SHADOW",
        "started_at": FORWARD_VALIDATION_STARTED_AT.isoformat(),
        "rule_version": RULE_VERSION,
        "primary_horizon_min": PRIMARY_HORIZON_MIN,
        "quantiles_recalculated": False,
        "H2": {
            "strategy": H2_NAME,
            "rule_hash": H2_RULE_HASH,
            "rule": H2_RULE,
            "readiness": "NOT_ENOUGH_FORWARD_DATA",
            "total": 0,
            "pending": 0,
            "complete": 0,
        },
        "H3": {
            "strategy": H3_NAME,
            "rule_hash": H3_RULE_HASH,
            "rule": H3_RULE,
            "readiness": "NOT_ENOUGH_FORWARD_DATA",
            "total": 0,
            "pending": 0,
            "complete": 0,
        },
    }
    if session is not None:
        try:
            forward["H2"] = readiness_for(session, strategy=H2_NAME)
            forward["H2"]["rule"] = H2_RULE
            forward["H3"] = readiness_for(session, strategy=H3_NAME)
            forward["H3"]["rule"] = H3_RULE
        except Exception as exc:  # noqa: BLE001
            forward["db_error"] = type(exc).__name__

    rt = runtime_status()
    return {
        "ok": True,
        "research_only": True,
        "work_id": "WRK-20260829-019-UPBIT-H2-H3-FROZEN-FORWARD-SHADOW",
        "historical": historical,
        "forward_shadow": forward,
        "runtime": rt,
        "safety": {
            "shadow_only": True,
            "strategy_signal_published": int(
                rt.get("strategy_signal_published") or 0
            ),
            "executor_calls": int(rt.get("executor_calls") or 0),
            "real_order_created_by_shadow": int(rt.get("real_orders") or 0),
            "user_approval_required": True,
            "auto_promotion": False,
        },
    }
