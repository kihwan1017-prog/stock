"""Run UBA1380 35RT exit/churn shadow replay — READ ONLY."""

from __future__ import annotations

import json
from pathlib import Path

from stock_platform.operation.upbit_opportunity_shadow.exit_churn_shadow_replay import (
    run_full_replay,
)

AUDIT = Path(".run/k_upbit_real_auto_trading_pnl_deep_audit.json")
OUT_JSON = Path(".run/k_upbit_exit_churn_shadow_replay.json")
OUT_MD = Path(".run/k_upbit_exit_churn_shadow_replay.md")


def _table_row(exp: dict) -> str:
    k = exp.get("kpis") or {}
    d = exp.get("diff_vs_e0") or {}
    return (
        f"| {exp.get('id')} | {exp.get('group')} | {k.get('sample_count', 0)} | "
        f"{k.get('win_rate')} | {k.get('net_pnl')} | {k.get('profit_factor')} | "
        f"{d.get('net_benefit_vs_e0', '—')} | {k.get('early_dump_count', '—')} | "
        f"{k.get('fee_churn_count', '—')} |"
    )


def main() -> None:
    report = run_full_replay(AUDIT)
    OUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    e0 = report["BASELINE_E0"]
    lines = [
        "# UPBIT Exit/Churn Shadow Replay — UBA1380",
        "",
        f"FINAL_VERDICT: **{report['FINAL_VERDICT']}**",
        "",
        "## BASELINE E0 (actual fills)",
        f"- N: {e0['sample_count']} · W/L: {e0['wins']}/{e0['losses']} · WR: {e0['win_rate']}",
        f"- Gross: {e0['gross_pnl']} · Fees: {e0['fees']} · **Net: {e0['net_pnl']}**",
        f"- PF: {e0['profit_factor']} · Expectancy: {e0.get('expectancy')}",
        f"- Early dump: {e0.get('early_dump_count')} · Fee churn: {e0.get('fee_churn_count')}",
        f"- E0 equality: {report['E0_EQUALITY_CHECK']['match']}",
        "",
        "## Exit experiments",
        "| ID | Grp | Trades | WR | Net | PF | ΔNet vs E0 | EarlyDump | FeeChurn |",
        "|----|-----|--------|----|-----|----|-----------|-----------|----------|",
    ]
    for exp in report["experiments"]:
        if exp.get("group") in {"E0", "E1", "E2", "E3"}:
            lines.append(_table_row(exp))
    lines.extend(
        [
            "",
            "## Entry experiments",
            "| ID | Grp | Trades | WR | Net | PF | ΔNet vs E0 | Skip | FeeChurn |",
            "|----|-----|--------|----|-----|----|-----------|------|----------|",
        ]
    )
    for exp in report["experiments"]:
        if exp.get("group") in {"E4", "E5", "E6"}:
            k = exp.get("kpis") or {}
            d = exp.get("diff_vs_e0") or {}
            lines.append(
                f"| {exp.get('id')} | {exp.get('group')} | {k.get('sample_count', 0)} | "
                f"{k.get('win_rate')} | {k.get('net_pnl')} | {k.get('profit_factor')} | "
                f"{d.get('net_benefit_vs_e0', '—')} | {k.get('skipped_entries', 0)} | "
                f"{k.get('fee_churn_count', '—')} |"
            )
    lines.extend(
        [
            "",
            "## Combinations (max 5)",
            "| ID | Trades | Net | ΔNet | Skip |",
            "|----|--------|-----|------|------|",
        ]
    )
    for exp in report["experiments"]:
        if exp.get("group") == "E7":
            k = exp.get("kpis") or {}
            d = exp.get("diff_vs_e0") or {}
            lines.append(
                f"| {exp.get('id')} | {k.get('sample_count')} | {k.get('net_pnl')} | "
                f"{d.get('net_benefit_vs_e0', '—')} | {k.get('skipped_entries', 0)} |"
            )
    lines.extend(
        [
            "",
            f"**BEST_EXIT_SHADOW (exit-only):** {report.get('BEST_EXIT_SHADOW')} "
            f"(ΔNet {report.get('BEST_EXIT_NET_BENEFIT')})",
            f"**BEST_ENTRY_SHADOW:** {report.get('BEST_ENTRY_SHADOW')} "
            f"(ΔNet {report.get('BEST_ENTRY_NET_BENEFIT')}) "
            f"⚠ trade_reduction={report.get('BEST_ENTRY_TRADE_REDUCTION_WARNING')}",
            f"**BEST_COMBINED:** {report.get('BEST_COMBINED_SHADOW')} "
            f"(Net {report.get('BEST_COMBINED_NET')})",
            "",
            f"REAL_PROMOTION: **NO** · SLIPPAGE: {report['SLIPPAGE_MODELED']}",
            f"NEXT: {report['NEXT_ACTION']}",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "FINAL_VERDICT": report["FINAL_VERDICT"],
                "E0_NET": e0["net_pnl"],
                "BEST_EXIT": report.get("BEST_EXIT_SHADOW"),
                "BEST_EXIT_BENEFIT": report.get("BEST_EXIT_NET_BENEFIT"),
                "BEST_COMBINED": report.get("BEST_COMBINED_SHADOW"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
