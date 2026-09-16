"""Load WRK-016 evidence for Admin research UI (read-only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CANDIDATES = (
    _REPO_ROOT / ".run" / "k_upbit_positive_edge_entry_discovery.json",
    Path.cwd() / ".run" / "k_upbit_positive_edge_entry_discovery.json",
)


def summarize_for_ui() -> dict[str, Any]:
    for path in _CANDIDATES:
        if not path.is_file():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            continue
        families = raw.get("ENTRY_FAMILY_RESULTS") or {}
        rows = []
        for key in (
            "M0_CURRENT",
            "MOMENTUM",
            "BREAKOUT",
            "VOLUME_SURGE",
            "PULLBACK",
            "MEAN_REVERSION",
            "BEST_MULTI_STRATEGY",
        ):
            row = families.get(key) or {}
            rows.append({"family": key, **row})
        return {
            "ok": True,
            "source_path": str(path),
            "research_only": True,
            "real_policy_changed": False,
            "work_id": raw.get("WORK_ID"),
            "verdict": raw.get("FINAL_VERDICT"),
            "classification": (raw.get("RECOMMENDATION") or {}).get(
                "CLASSIFICATION"
            ),
            "data": raw.get("DATA"),
            "regime": raw.get("REGIME"),
            "families": rows,
            "fixed_horizon": raw.get("FIXED_HORIZON"),
            "walk_forward": raw.get("WALK_FORWARD"),
            "multi_strategy": raw.get("MULTI_STRATEGY"),
            "ai": raw.get("AI_PREDICTIVE_VALUE"),
            "recommendation": raw.get("RECOMMENDATION"),
            "auto_slot": raw.get("AUTO_SLOT"),
            "production": raw.get("PRODUCTION"),
        }
    return {
        "ok": False,
        "message": "WRK-016 evidence missing — run discovery script",
        "research_only": True,
        "real_policy_changed": False,
    }
