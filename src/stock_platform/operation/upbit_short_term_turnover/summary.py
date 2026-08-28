"""Load latest WRK-015 short-term turnover research evidence (read-only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Repo root = parents[4]: .../src/stock_platform/operation/upbit_short_term_turnover
_REPO_ROOT = Path(__file__).resolve().parents[4]
_EVIDENCE_CANDIDATES = (
    _REPO_ROOT / ".run" / "k_upbit_short_term_turnover_research.json",
    Path.cwd() / ".run" / "k_upbit_short_term_turnover_research.json",
)


def load_turnover_research_evidence() -> dict[str, Any]:
    """Evidence JSON 로드. 없으면 빈 스텁 (REAL 무관)."""

    for path in _EVIDENCE_CANDIDATES:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {
                    "ok": True,
                    "source_path": str(path),
                    "real_policy_changed": False,
                    "research_only": True,
                    "report": raw,
                }
    return {
        "ok": False,
        "source_path": None,
        "real_policy_changed": False,
        "research_only": True,
        "report": None,
        "message": "Evidence file not found — run WRK-015 research script first",
    }


def summarize_for_ui() -> dict[str, Any]:
    """Admin UI용 요약."""

    loaded = load_turnover_research_evidence()
    report = loaded.get("report") or {}
    if not report:
        return loaded
    comparison = report.get("STRATEGY_COMPARISON") or {}
    profiles = []
    for key in (
        "BASELINE",
        "CONSERVATIVE_TURNOVER",
        "BALANCED_TURNOVER",
        "AGGRESSIVE_TURNOVER",
    ):
        row = comparison.get(key) or {}
        profiles.append(
            {
                "profile": key,
                "trades_per_day": row.get("trades_per_day"),
                "zero_trade_days_pct": row.get("zero_trade_days_pct"),
                "median_holding_minutes": row.get("median_holding_minutes"),
                "win_rate": row.get("win_rate"),
                "profit_factor": row.get("profit_factor"),
                "gross_pnl": row.get("gross_pnl"),
                "fees": row.get("fees"),
                "slippage": row.get("slippage"),
                "net_pnl": row.get("net_pnl"),
                "max_drawdown": row.get("max_drawdown"),
            }
        )
    return {
        "ok": True,
        "source_path": loaded.get("source_path"),
        "real_policy_changed": False,
        "research_only": True,
        "work_id": report.get("WORK_ID"),
        "verdict": report.get("FINAL_VERDICT"),
        "data": report.get("DATA"),
        "bottlenecks": report.get("CURRENT_BOTTLENECKS"),
        "baseline": report.get("CURRENT_BASELINE"),
        "auto_slot": report.get("AUTO_SLOT"),
        "ai": report.get("AI"),
        "recommendation": report.get("RECOMMENDATION"),
        "profiles": profiles,
        "exit_grid_best": {
            "BEST_TP": (report.get("EXIT_GRID") or {}).get("BEST_TP"),
            "BEST_SL": (report.get("EXIT_GRID") or {}).get("BEST_SL"),
            "BEST_TRAILING": (report.get("EXIT_GRID") or {}).get("BEST_TRAILING"),
            "BEST_TIME_EXIT": (report.get("EXIT_GRID") or {}).get(
                "BEST_TIME_EXIT"
            ),
        },
        "policy_decisions": report.get("POLICY_DECISIONS"),
        "production": report.get("PRODUCTION"),
    }
