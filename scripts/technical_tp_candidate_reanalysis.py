"""READ-ONLY: ORIGINAL DISCOVERY TP 2/3/4 vs 6% reanalysis (post coverage remediation).

No settings mutation. No DB writes. No candle sync. POST_COV 53+ excluded from selection.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select  # noqa: E402

from stock_platform.database.session import get_session_factory  # noqa: E402
from stock_platform.operation.upbit_opportunity_shadow.candle_loader import (  # noqa: E402
    list_minute_bars_db,
)
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (  # noqa: E402
    as_utc,
    compute_mfe_mae,
    compute_tp_sl,
)
from stock_platform.operation.upbit_opportunity_shadow.cohort_milestone import (  # noqa: E402
    _is_valid_cohort_row,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (  # noqa: E402
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (  # noqa: E402
    UpbitOpportunityShadowEntity,
)

CUTOFF = datetime.fromisoformat("2026-08-14T23:25:40.424+00:00")
MAX_SHADOW_ID = 51
SL_PCT = 3.0
TP_SET = (2.0, 3.0, 4.0, 6.0)
BASE_TP = 6.0
OUT_JSON = ROOT / "docs" / "audit" / "TECHNICAL_TP_CANDIDATE_REANALYSIS.json"
EXPECTED_COMPLETED = 50
EXPECTED_STRICT = 47


def _r(v: float | None, nd: int = 4) -> float | None:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), nd)


def _stats(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {"n": 0}
    n = len(vals)
    pos = sum(1 for v in vals if v > 0)
    neg = sum(1 for v in vals if v < 0)
    return {
        "n": n,
        "mean": _r(sum(vals) / n),
        "median": _r(float(statistics.median(vals))),
        "positive_rate": _r(pos / n),
        "loss_rate": _r(neg / n),
        "min": _r(min(vals)),
        "max": _r(max(vals)),
    }


def _exit_return(
    *,
    entry: Decimal,
    bars: list[Any],
    detected: datetime,
    terminal: datetime,
    now: datetime,
    tp_pct: float,
    sl_pct: float,
) -> dict[str, Any]:
    tp_sl = compute_tp_sl(
        bars,
        entry=entry,
        start_at=detected,
        end_at=terminal,
        now=now,
        tp_pct=tp_pct,
        sl_pct=sl_pct,
    )
    mfe, mae, _ = compute_mfe_mae(
        bars,
        entry=entry,
        start_at=detected,
        end_at=terminal,
        now=now,
    )
    tp_price = entry * (Decimal("1") + Decimal(str(abs(tp_pct))) / Decimal("100"))
    sl_price = entry * (Decimal("1") - Decimal(str(abs(sl_pct))) / Decimal("100"))

    first = tp_sl.first_hit
    exit_px: Decimal | None = None
    exit_kind = "TIMEOUT"
    if first in {"SL", "SAME_CANDLE_SL_CONSERVATIVE"}:
        exit_px = sl_price
        exit_kind = first
    elif first == "TP":
        exit_px = tp_price
        exit_kind = "TP"
    else:
        ordered = sorted(
            (
                b
                for b in bars
                if as_utc(detected) <= as_utc(b.candle_at) <= as_utc(terminal)
            ),
            key=lambda b: as_utc(b.candle_at),
        )
        if ordered:
            exit_px = ordered[-1].close
            exit_kind = "TIMEOUT"
        else:
            return {
                "ok": False,
                "reason": "NO_EXIT_BAR",
                "first_hit": first,
                "tp_hit": tp_sl.tp_hit,
                "sl_hit": tp_sl.sl_hit,
            }

    ret = float((exit_px - entry) / entry * Decimal("100"))
    mfe_f = float(mfe) if mfe is not None else None
    mae_f = float(mae) if mae is not None else None
    return {
        "ok": True,
        "exit_return_pct": ret,
        "exit_kind": exit_kind,
        "first_hit": first,
        "tp_hit": bool(tp_sl.tp_hit),
        "sl_hit": bool(tp_sl.sl_hit),
        "same_candle": first == "SAME_CANDLE_SL_CONSERVATIVE",
        "mfe_pct": mfe_f,
        "mae_pct": mae_f,
        "bars_checked": (tp_sl.detail or {}).get("bars_checked"),
    }


def _exclusion_reason(row: UpbitOpportunityShadowEntity) -> str:
    missing = [
        m
        for m in (5, 15, 30, 60)
        if getattr(row, f"return_{m}m_pct", None) is None
    ]
    if missing:
        return f"RETURN_WINDOW_MISSING:{','.join(str(m) for m in missing)}"
    if row.mfe_pct is None or row.mae_pct is None:
        return "MFE_MAE_MISSING"
    if row.tp_hit is None or row.sl_hit is None:
        return "TP_SL_FLAG_MISSING"
    watch = (row.evaluation_detail or {}).get("mismatch_watch") or {}
    if watch.get("code") == "SHADOW_EVALUATION_MISMATCH":
        return "SHADOW_EVALUATION_MISMATCH"
    return "NOT_STRICT"


def _concentration_level(any_sign_flip: bool, top_share: float) -> str:
    if any_sign_flip or top_share >= 0.5:
        return "HIGH"
    if top_share >= 0.3:
        return "MEDIUM"
    return "LOW"


def _robustness(any_sign_flip: bool, overall_mean: float) -> str:
    if overall_mean >= 0:
        # candidate mean advantage (or tie) — flip means fragile
        return "FRAGILE" if any_sign_flip else "ROBUST"
    # overall negative vs baseline — sign flip to positive is also fragile interpretation
    return "FRAGILE" if any_sign_flip else "ROBUST"


def _gate(
    *,
    tp: float,
    summary: dict[str, Any],
    base: dict[str, Any],
    delta: dict[str, Any],
    conc: dict[str, Any],
) -> dict[str, Any]:
    mean_adv = (summary["exit_return"].get("mean") or 0) > (
        base["exit_return"].get("mean") or 0
    )
    # "명확히 우수" — 양수 delta mean (epsilon 0.01pp)
    clear_mean = (delta.get("delta_mean_return") or 0) > 0.01
    median_ok = (summary["exit_return"].get("median") or 0) >= (
        (base["exit_return"].get("median") or 0) - 1e-12
    )
    loss_ok = (summary["exit_return"].get("loss_rate") or 0) <= (
        (base["exit_return"].get("loss_rate") or 0) + 0.02
    )
    mae_cand = summary["mae"].get("mean")
    mae_base = base["mae"].get("mean")
    # MAE는 음수(낙폭); 더 작은(더 음수)면 악화
    mae_ok = True
    if mae_cand is not None and mae_base is not None:
        mae_ok = mae_cand >= (mae_base - 0.05)

    conc_level = conc.get("concentration_level")
    robust = conc.get("loso_robustness")
    conc_ok = conc_level != "HIGH" and robust != "FRAGILE"

    # TP-hit만 좋아진 결과 금지: mean 우위 없이 hit만 상승
    hit_only = (not clear_mean) and (delta.get("delta_tp_hit_rate") or 0) > 0

    same_c = summary.get("same_candle_ambiguous_n") or 0
    same_ok = same_c == 0  # 결론을 좌우하지 않음 — 0이면 명확 PASS

    checks = {
        "A_clear_mean_advantage": bool(clear_mean and mean_adv),
        "B_median_not_worse": bool(median_ok),
        "C_loss_rate_not_worse": bool(loss_ok),
        "D_mae_downside_ok": bool(mae_ok),
        "E_concentration_not_high_fragile": bool(conc_ok),
        "F_not_tp_hit_only": bool(not hit_only),
        "G_same_candle_ok": bool(same_ok),
    }
    passed = all(checks.values())
    return {
        "tp_pct": tp,
        "checks": checks,
        "passed": passed,
        "fail_reasons": [k for k, v in checks.items() if not v],
    }


def main() -> int:
    session = get_session_factory()()
    try:
        # --- contamination inventory (not used in selection) ---
        all_rows = list(
            session.scalars(
                select(UpbitOpportunityShadowEntity).where(
                    UpbitOpportunityShadowEntity.deleted_at.is_(None)
                )
            )
        )
        post_cov = [
            r
            for r in all_rows
            if r.status == SHADOW_STATUS_COMPLETED and int(r.shadow_id) >= 53
        ]
        shadow52 = next((r for r in all_rows if int(r.shadow_id) == 52), None)

        # --- discovery under ORIGINAL cutoff ---
        le51_completed = [
            r
            for r in all_rows
            if r.status == SHADOW_STATUS_COMPLETED and int(r.shadow_id) <= MAX_SHADOW_ID
        ]
        discovery = [
            r
            for r in le51_completed
            if r.completed_at is not None and as_utc(r.completed_at) <= CUTOFF
        ]
        after_cutoff = [
            r
            for r in le51_completed
            if r.completed_at is not None and as_utc(r.completed_at) > CUTOFF
        ]
        strict = [r for r in discovery if _is_valid_cohort_row(r)]
        excluded = [
            {
                "shadow_id": int(r.shadow_id),
                "symbol": str(r.symbol),
                "exclusion_reason": _exclusion_reason(r),
            }
            for r in discovery
            if not _is_valid_cohort_row(r)
        ]

        sample_ok = (
            len(discovery) == EXPECTED_COMPLETED and len(strict) == EXPECTED_STRICT
        )
        if not sample_ok:
            payload = {
                "mode": "READ_ONLY",
                "SAMPLE_RECONCILIATION": "FAIL",
                "counts": {
                    "DISCOVERY_COMPLETED": len(discovery),
                    "DISCOVERY_STRICT_VALID": len(strict),
                    "expected_completed": EXPECTED_COMPLETED,
                    "expected_strict": EXPECTED_STRICT,
                },
                "excluded_from_strict": excluded,
                "after_cutoff_le51": [
                    {
                        "shadow_id": int(r.shadow_id),
                        "symbol": str(r.symbol),
                        "completed_at": as_utc(r.completed_at).isoformat(),
                    }
                    for r in after_cutoff
                ],
                "note": "Sample mismatch — TP comparison aborted",
            }
            OUT_JSON.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps({"ok": False, "SAMPLE_RECONCILIATION": "FAIL"}, ensure_ascii=False))
            return 2

        per_tp: dict[float, dict[str, Any]] = {
            tp: {"rows": {}, "invalid": 0, "missing_bars": 0, "ambiguous": 0}
            for tp in TP_SET
        }
        now = datetime.now(timezone.utc) + timedelta(days=1)

        for row in strict:
            # 안전: POST_COV / 52 절대 미포함
            sid = int(row.shadow_id)
            assert sid <= MAX_SHADOW_ID and sid != 52
            detected = as_utc(row.detected_at)
            terminal = detected + timedelta(minutes=60)
            entry = Decimal(str(row.entry_price))
            bars = list_minute_bars_db(
                session,
                symbol=str(row.symbol),
                start_at=detected - timedelta(minutes=1),
                end_at=terminal,
                timeframe=1,
            )
            if len(bars) < 5:
                for tp in TP_SET:
                    per_tp[tp]["missing_bars"] += 1
                    per_tp[tp]["rows"][sid] = {
                        "ok": False,
                        "reason": "MISSING_BARS",
                        "symbol": row.symbol,
                        "n_bars": len(bars),
                    }
                continue
            for tp in TP_SET:
                res = _exit_return(
                    entry=entry,
                    bars=bars,
                    detected=detected,
                    terminal=terminal,
                    now=now,
                    tp_pct=tp,
                    sl_pct=SL_PCT,
                )
                res["symbol"] = row.symbol
                res["shadow_id"] = sid
                if res.get("same_candle"):
                    per_tp[tp]["ambiguous"] += 1
                if not res.get("ok"):
                    per_tp[tp]["invalid"] += 1
                per_tp[tp]["rows"][sid] = res

        ok_sets = [
            {sid for sid, r in per_tp[tp]["rows"].items() if r.get("ok")}
            for tp in TP_SET
        ]
        paired_ids = sorted(set.intersection(*ok_sets) if ok_sets else set())

        def summarize(tp: float) -> dict[str, Any]:
            rets = [float(per_tp[tp]["rows"][sid]["exit_return_pct"]) for sid in paired_ids]
            mfes = [
                float(per_tp[tp]["rows"][sid]["mfe_pct"])
                for sid in paired_ids
                if per_tp[tp]["rows"][sid].get("mfe_pct") is not None
            ]
            maes = [
                float(per_tp[tp]["rows"][sid]["mae_pct"])
                for sid in paired_ids
                if per_tp[tp]["rows"][sid].get("mae_pct") is not None
            ]
            first_tp = sum(
                1 for sid in paired_ids if per_tp[tp]["rows"][sid].get("exit_kind") == "TP"
            )
            sl_hits = sum(
                1
                for sid in paired_ids
                if per_tp[tp]["rows"][sid].get("exit_kind")
                in {"SL", "SAME_CANDLE_SL_CONSERVATIVE"}
            )
            timeouts = sum(
                1
                for sid in paired_ids
                if per_tp[tp]["rows"][sid].get("exit_kind") == "TIMEOUT"
            )
            same_c = sum(
                1 for sid in paired_ids if per_tp[tp]["rows"][sid].get("same_candle")
            )
            n = len(paired_ids)
            return {
                "tp_pct": tp,
                "paired_n": n,
                "exit_return": _stats(rets),
                "mfe": _stats(mfes),
                "mae": _stats(maes),
                "tp_hit_count": first_tp,
                "tp_hit_rate": _r(first_tp / n) if n else None,
                "sl_exit_count": sl_hits,
                "sl_exit_rate": _r(sl_hits / n) if n else None,
                "timeout_count": timeouts,
                "timeout_rate": _r(timeouts / n) if n else None,
                "same_candle_ambiguous_n": same_c,
                "missing_bars_rows": per_tp[tp]["missing_bars"],
                "invalid_rows": per_tp[tp]["invalid"],
            }

        summaries = {str(tp): summarize(tp) for tp in TP_SET}

        deltas: dict[str, Any] = {}
        for tp in (2.0, 3.0, 4.0):
            better = worse = equal = 0
            row_deltas: list[float] = []
            for sid in paired_ids:
                a = float(per_tp[tp]["rows"][sid]["exit_return_pct"])
                b = float(per_tp[BASE_TP]["rows"][sid]["exit_return_pct"])
                d = a - b
                row_deltas.append(d)
                if abs(d) < 1e-12:
                    equal += 1
                elif d > 0:
                    better += 1
                else:
                    worse += 1
            deltas[str(tp)] = {
                "paired_delta_mean": _r(sum(row_deltas) / len(row_deltas)),
                "paired_delta_median": _r(float(statistics.median(row_deltas))),
                "delta_mean_return": _r(
                    (summaries[str(tp)]["exit_return"].get("mean") or 0)
                    - (summaries[str(BASE_TP)]["exit_return"].get("mean") or 0)
                ),
                "delta_median_return": _r(
                    (summaries[str(tp)]["exit_return"].get("median") or 0)
                    - (summaries[str(BASE_TP)]["exit_return"].get("median") or 0)
                ),
                "delta_positive_rate": _r(
                    (summaries[str(tp)]["exit_return"].get("positive_rate") or 0)
                    - (summaries[str(BASE_TP)]["exit_return"].get("positive_rate") or 0)
                ),
                "delta_loss_rate": _r(
                    (summaries[str(tp)]["exit_return"].get("loss_rate") or 0)
                    - (summaries[str(BASE_TP)]["exit_return"].get("loss_rate") or 0)
                ),
                "delta_tp_hit_rate": _r(
                    (summaries[str(tp)].get("tp_hit_rate") or 0)
                    - (summaries[str(BASE_TP)].get("tp_hit_rate") or 0)
                ),
                "candidate_better_row_count": better,
                "baseline_better_row_count": worse,
                "equal_row_count": equal,
            }

        concentration: dict[str, Any] = {}
        for tp in (2.0, 3.0, 4.0):
            by_sym: dict[str, list[float]] = defaultdict(list)
            for sid in paired_ids:
                sym = str(per_tp[tp]["rows"][sid]["symbol"])
                a = float(per_tp[tp]["rows"][sid]["exit_return_pct"])
                b = float(per_tp[BASE_TP]["rows"][sid]["exit_return_pct"])
                by_sym[sym].append(a - b)
            abs_total = sum(abs(x) for xs in by_sym.values() for x in xs) or 1.0
            sym_rows = []
            for sym, ds in sorted(by_sym.items(), key=lambda kv: -abs(sum(kv[1]))):
                s = sum(ds)
                sym_rows.append(
                    {
                        "symbol": sym,
                        "n": len(ds),
                        "sum_delta": _r(s),
                        "mean_delta": _r(s / len(ds)),
                        "abs_share": _r(abs(s) / abs_total),
                    }
                )
            overall_mean = (
                sum(
                    float(per_tp[tp]["rows"][sid]["exit_return_pct"])
                    - float(per_tp[BASE_TP]["rows"][sid]["exit_return_pct"])
                    for sid in paired_ids
                )
                / len(paired_ids)
            )
            loco = []
            for drop_sym in sorted(by_sym.keys()):
                keep = [
                    sid
                    for sid in paired_ids
                    if str(per_tp[tp]["rows"][sid]["symbol"]) != drop_sym
                ]
                if len(keep) < 5:
                    continue
                m = sum(
                    float(per_tp[tp]["rows"][sid]["exit_return_pct"])
                    - float(per_tp[BASE_TP]["rows"][sid]["exit_return_pct"])
                    for sid in keep
                ) / len(keep)
                loco.append(
                    {
                        "drop_symbol": drop_sym,
                        "remaining_n": len(keep),
                        "paired_delta_mean": _r(m),
                        "sign_flip_vs_overall": (overall_mean > 0 and m <= 0)
                        or (overall_mean < 0 and m >= 0),
                    }
                )
            any_flip = any(x["sign_flip_vs_overall"] for x in loco)
            top_share = float(sym_rows[0]["abs_share"] or 0) if sym_rows else 0.0
            level = _concentration_level(any_flip, top_share)
            rob = _robustness(any_flip, overall_mean)
            # overall mean negative → not an advantage case; mark FRAGILE if flips, else ROBUST on negative
            if overall_mean < 0 and not any_flip:
                rob = "ROBUST"  # stably worse than baseline
            elif overall_mean < 0 and any_flip:
                rob = "INCONCLUSIVE"
            concentration[str(tp)] = {
                "by_symbol": sym_rows[:12],
                "top_symbol": sym_rows[0] if sym_rows else None,
                "leave_one_symbol_out": loco,
                "any_sign_flip": any_flip,
                "concentration_level": level,
                "loso_robustness": rob,
                "overall_paired_delta_mean": _r(overall_mean),
            }

        gates = {
            str(tp): _gate(
                tp=tp,
                summary=summaries[str(tp)],
                base=summaries[str(BASE_TP)],
                delta=deltas[str(tp)],
                conc=concentration[str(tp)],
            )
            for tp in (2.0, 3.0, 4.0)
        }
        passed = [tp for tp, g in gates.items() if g["passed"]]

        if len(passed) == 1:
            frozen: float | None = float(passed[0])
            decision = f"FROZEN_CANDIDATE_TP={frozen}"
            reason = "SINGLE_CANDIDATE_PASSED_GATES"
        elif len(passed) > 1:
            # primary metric + robustness: pick best mean among non-fragile
            ranked = sorted(
                passed,
                key=lambda t: (
                    concentration[t]["loso_robustness"] != "ROBUST",
                    -(summaries[t]["exit_return"].get("mean") or -999),
                ),
            )
            frozen = float(ranked[0])
            decision = f"FROZEN_CANDIDATE_TP={frozen}"
            reason = "MULTI_PASS_SELECTED_BY_PRIMARY_AND_ROBUSTNESS"
        else:
            frozen = None
            # reason taxonomy
            means = {
                tp: summaries[str(tp)]["exit_return"].get("mean") or 0
                for tp in (2.0, 3.0, 4.0)
            }
            base_mean = summaries[str(BASE_TP)]["exit_return"].get("mean") or 0
            if all(m < base_mean for m in means.values()):
                reason = "KEEP_6_SUPERIOR"
            elif all((deltas[str(tp)].get("delta_mean_return") or 0) <= 0.01 for tp in (2.0, 3.0, 4.0)):
                reason = "NO_MEAN_ADVANTAGE"
            else:
                # some mean edge but gate fail
                fail_sets = [set(gates[str(tp)]["fail_reasons"]) for tp in (2.0, 3.0, 4.0)]
                if any("E_concentration_not_high_fragile" in f for f in fail_sets) and any(
                    (deltas[str(tp)].get("delta_mean_return") or 0) > 0.01 for tp in (2.0, 3.0, 4.0)
                ):
                    reason = "CONCENTRATION_FAIL"
                elif any("C_loss_rate_not_worse" in f or "D_mae_downside_ok" in f for f in fail_sets):
                    reason = "DOWNSIDE_GUARD_FAIL"
                else:
                    reason = "INSUFFICIENT_EVIDENCE"
            decision = "FROZEN_CANDIDATE_TP=null"

        # selection ids must not include post_cov / 52
        used_ids = set(paired_ids)
        post_cov_ids = {int(r.shadow_id) for r in post_cov}
        contamination = len(used_ids & post_cov_ids)
        used_52 = 52 in used_ids

        payload = {
            "step": "TECHNICAL_TP_CANDIDATE_REANALYSIS",
            "mode": "READ_ONLY_ANALYSIS",
            "date": "2026-08-15",
            "HEAD": "5c6ad67",
            "discovery_cutoff": CUTOFF.isoformat(),
            "max_shadow_id": MAX_SHADOW_ID,
            "baseline_tp_pct": BASE_TP,
            "candidate_set_pct": [2.0, 3.0, 4.0],
            "sl_pct": SL_PCT,
            "evaluator_policy": "SAME_CANDLE_SL_CONSERVATIVE",
            "candle_source": "market.candle_minute DB only (no sync, no synthetic)",
            "fee_slippage": False,
            "look_ahead_violation": 0,
            "raw_coverage_exclusion_applied": False,
            "SAMPLE_RECONCILIATION": "PASS",
            "counts": {
                "DISCOVERY_COMPLETED": len(discovery),
                "DISCOVERY_STRICT_VALID": len(strict),
                "PAIRED_VALID_N": len(paired_ids),
                "excluded_strict_n": len(excluded),
            },
            "excluded_from_strict": excluded,
            "post_discovery_pre_cov": [
                {
                    "shadow_id": int(r.shadow_id),
                    "symbol": str(r.symbol),
                    "completed_at": as_utc(r.completed_at).isoformat(),
                    "used_for_selection": False,
                }
                for r in after_cutoff
            ],
            "summaries": summaries,
            "deltas_vs_6": deltas,
            "concentration": concentration,
            "candidate_gates": gates,
            "FINAL_CANDIDATE_DECISION": decision,
            "FROZEN_CANDIDATE_TP": frozen,
            "decision_reason": reason,
            "POST_COV_ROWS_AVAILABLE": len(post_cov),
            "POST_COV_ROWS_USED_FOR_SELECTION": 0,
            "OOS_CONTAMINATION": contamination,
            "shadow52_used_for_selection": used_52,
            "OOS_CANDIDATE_FREEZE_READY": frozen is not None,
            "OOS_START_READY": False,
            "CURRENT_TP": 6.0,
            "CURRENT_SL": 3.0,
            "production_tp_mutation": 0,
            "db_mutation": 0,
            "paired_shadow_ids": paired_ids,
            "oos_freeze_package_proposal": None
            if frozen is None
            else {
                "candidate_tp_pct": frozen,
                "baseline_tp_pct": 6.0,
                "sl_pct": 3.0,
                "discovery_cutoff": CUTOFF.isoformat(),
                "primary_metric": "paired_counterfactual_exit_return_pct",
                "guards": [
                    "median_return",
                    "loss_rate",
                    "MAE",
                    "SL_exit",
                    "symbol_concentration",
                    "same_candle_ambiguity",
                    "path_quality_provenance",
                ],
                "note": "proposal only — OOS not started this STEP",
            },
        }
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "SAMPLE_RECONCILIATION": "PASS",
                    "PAIRED_VALID_N": len(paired_ids),
                    "FROZEN_CANDIDATE_TP": frozen,
                    "decision_reason": reason,
                    "out": str(OUT_JSON),
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        session.rollback()
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
