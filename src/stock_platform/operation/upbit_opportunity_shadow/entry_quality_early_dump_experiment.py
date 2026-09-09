"""CLEAN Shadow Entry Quality — Early Dump filter A/B (RESEARCH ONLY).

REAL Entry/Exit/Risk/Slot 변경·자동 승격 금지.
Promotion KPI = CLEAN_FORWARD only (Legacy 459 / backfill 제외).
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    TARGET_CLEAN_MIN,
    TARGET_CLEAN_RECOMMENDED,
    assign_clean_forward_obs,
    partition_forward_rows,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
    ForwardObs,
    arm_kpi,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_policy_ab import (
    ENTRY_BASELINE_SPEC,
)

# ── Sample gates (promotion 자동 금지) ──────────────────────────────────────
GATE_COLLECTION = "COLLECTION_ONLY"  # N < 100
GATE_DIAGNOSTIC = "DIAGNOSTIC_ONLY"  # N >= 100
GATE_PRIMARY = "PRIMARY_REVIEW"  # N >= 500
GATE_RECOMMENDED = "RECOMMENDED_REVIEW"  # N >= 1000

N_COLLECTION = 100
N_PRIMARY = TARGET_CLEAN_MIN  # 500
N_RECOMMENDED = TARGET_CLEAN_RECOMMENDED  # 1000

# REAL 14 RT reference (합산 금지 — 표시만)
REAL_14_REFERENCE = {
    "rt": 14,
    "wins": 3,
    "losses": 11,
    "net_krw": -270.22,
    "pf": 0.32,
    "entry_bad": 4,
    "early_dump": 4,
    "fee_churn": 5,
    "mfe_median_pct": 0.09,
    "verdict": "FOCUS_ENTRY_FIRST",
    "note": "REAL Broker fills reference only — never merge into Shadow KPI",
}

# Round-trip fee proxy on ~10k notional ≈ 0.10%
FEE_RT_PCT_THRESHOLD = 0.10

# Fixed buckets only — no grid search
E1_RSI_MAX = 65.0
E2_MIN_MA_SEP_PCT = 0.15
E3_PRE5_SPIKE_PCT = 0.50
E3_PRE3_SPIKE_PCT = 0.40
E4_NEAR_HIGH_PCT = -0.15  # dist_from_15m_high >= -0.15 → chase
E5_VOL_EXHAUSTION = 2.5


def _avg(vals: Sequence[float]) -> float | None:
    return round(sum(vals) / len(vals), 6) if vals else None


def _median(vals: Sequence[float]) -> float | None:
    return float(statistics.median(vals)) if vals else None


def _feat_num(features: dict[str, Any], key: str) -> float | None:
    v = features.get(key)
    if v is None or v == "NOT_AVAILABLE":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def sample_gate(clean_n: int) -> str:
    if clean_n >= N_RECOMMENDED:
        return GATE_RECOMMENDED
    if clean_n >= N_PRIMARY:
        return GATE_PRIMARY
    if clean_n >= N_COLLECTION:
        return GATE_DIAGNOSTIC
    return GATE_COLLECTION


def outcome_label(o: ForwardObs) -> str:
    """Diagnostic path label — REAL 자동 적용 금지."""

    feat = o.features or {}
    r3 = _feat_num(feat, "return_3m")
    r5 = _feat_num(feat, "return_5m")
    mfe = o.mfe_pct

    if r3 is not None and r3 <= -0.3:
        return "EARLY_DUMP_3M"
    if r5 is not None and r5 <= -0.5:
        return "EARLY_DUMP_5M"
    if mfe is not None and mfe >= 0.5 and r5 is not None and r5 >= 0.2:
        return "GOOD_FOLLOW_THROUGH"
    if (
        mfe is not None
        and mfe >= 0.5
        and r5 is not None
        and r5 < mfe * 0.4
    ):
        return "SPIKE_REVERSAL"
    if (mfe is None or abs(mfe) < 0.2) and (r5 is None or abs(r5) < 0.25):
        return "FLAT"
    if o.early_dump:
        return "EARLY_DUMP_5M"
    return "FLAT"


@dataclass(frozen=True, slots=True)
class FilterSpec:
    code: str
    name_ko: str
    description: str
    # True = keep (accept); False = filter out
    accept_fn: Callable[[ForwardObs], bool]
    # Missing feature → fail-open (keep) unless baseline already failed
    require_feature: bool = False


def _pass_e1(o: ForwardObs) -> bool:
    r = o.metrics.rsi14
    if r is None:
        return True  # fail-open on missing
    return float(r) <= E1_RSI_MAX


def _pass_e2(o: ForwardObs) -> bool:
    s = o.metrics.ma_separation_pct
    if s is None:
        return True
    return float(s) >= E2_MIN_MA_SEP_PCT


def _pass_e3(o: ForwardObs) -> bool:
    pre5 = _feat_num(o.features, "pre_entry_return_5m")
    pre3 = _feat_num(o.features, "pre_entry_return_3m")
    if pre5 is None and pre3 is None:
        return True
    if pre5 is not None and pre5 >= E3_PRE5_SPIKE_PCT:
        return False
    if pre3 is not None and pre3 >= E3_PRE3_SPIKE_PCT:
        return False
    return True


def _pass_e4(o: ForwardObs) -> bool:
    d = _feat_num(o.features, "dist_from_15m_high_pct")
    if d is None:
        return True
    # near local high (within 0.15% of high)
    return d < E4_NEAR_HIGH_PCT


def _pass_e5(o: ForwardObs) -> bool:
    v = o.metrics.volume_surge
    if v is None:
        return True
    return float(v) < E5_VOL_EXHAUSTION


FILTER_SPECS: dict[str, FilterSpec] = {
    "E1": FilterSpec(
        "E1",
        "RSI 고점 필터",
        f"RSI > {E1_RSI_MAX} 거부",
        _pass_e1,
    ),
    "E2": FilterSpec(
        "E2",
        "MA 이격 최소",
        f"MA separation < {E2_MIN_MA_SEP_PCT}% 거부",
        _pass_e2,
    ),
    "E3": FilterSpec(
        "E3",
        "진입 전 스파이크 거부",
        f"pre5>={E3_PRE5_SPIKE_PCT}% 또는 pre3>={E3_PRE3_SPIKE_PCT}% 거부",
        _pass_e3,
    ),
    "E4": FilterSpec(
        "E4",
        "고점 추격 거부",
        f"15m high 이격 >= {E4_NEAR_HIGH_PCT}% (고점 근접) 거부",
        _pass_e4,
    ),
    "E5": FilterSpec(
        "E5",
        "거래량 소진 거부",
        f"volume_surge >= {E5_VOL_EXHAUSTION} 거부",
        _pass_e5,
    ),
}


def _combine(*fns: Callable[[ForwardObs], bool]) -> Callable[[ForwardObs], bool]:
    def _fn(o: ForwardObs) -> bool:
        return all(f(o) for f in fns)

    return _fn


def evaluate_filter_arm(
    baseline_accepted: Sequence[ForwardObs],
    *,
    code: str,
    name_ko: str,
    accept_fn: Callable[[ForwardObs], bool],
) -> dict[str, Any]:
    """Baseline 통과분 위에서 추가 filter 평가."""

    total = len(baseline_accepted)
    accepted = [o for o in baseline_accepted if accept_fn(o)]
    filtered = [o for o in baseline_accepted if not accept_fn(o)]

    avoided = [o for o in filtered if float(o.outcome.get("net_pnl_krw") or 0) < 0]
    missed = [o for o in filtered if float(o.outcome.get("net_pnl_krw") or 0) > 0]
    avoided_v = abs(sum(float(o.outcome.get("net_pnl_krw") or 0) for o in avoided))
    missed_v = sum(float(o.outcome.get("net_pnl_krw") or 0) for o in missed)
    benefit = avoided_v - missed_v

    # KPI from accepted outcomes directly (already baseline-eligible)
    nets = [float(o.outcome.get("net_pnl_krw") or 0) for o in accepted]
    wins = sum(1 for n in nets if n > 0)
    losses = sum(1 for n in nets if n < 0)
    early = sum(1 for o in accepted if o.early_dump)
    mfe = [float(o.mfe_pct) for o in accepted if o.mfe_pct is not None]
    mae = [float(o.mae_pct) for o in accepted if o.mae_pct is not None]
    gp = sum(n for n in nets if n > 0)
    gl = abs(sum(n for n in nets if n < 0))
    kpi = {
        "entries": len(accepted),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(accepted), 4) if accepted else None,
        "net_pnl": round(sum(nets), 4) if accepted else 0.0,
        "profit_factor": round(gp / gl, 4) if gl > 0 else None,
        "avg_mfe": _avg(mfe),
        "median_mfe": _median(mfe),
        "avg_mae": _avg(mae),
        "median_mae": _median(mae),
        "early_dump_rate": round(early / len(accepted), 4) if accepted else None,
        "early_dump_count": early,
        "fee_only_loss_count": sum(
            1
            for o in accepted
            if abs(float(o.outcome.get("gross_pnl_krw") or 0)) < 1e-9
            and float(o.outcome.get("net_pnl_krw") or 0) < 0
        ),
    }

    labels = Counter(outcome_label(o) for o in accepted)
    reduction = (
        round((1.0 - len(accepted) / total) * 100, 2) if total else None
    )
    fee_est = round(
        sum(float(o.outcome.get("estimated_fee_krw") or 0) for o in accepted), 4
    )

    return {
        "code": code,
        "name_ko": name_ko,
        "total_baseline_candidates": total,
        "accepted": len(accepted),
        "filtered": len(filtered),
        "entry_count_reduction_pct": reduction,
        "avoided_losers": len(avoided),
        "avoided_loser_value": round(avoided_v, 4),
        "missed_winners": len(missed),
        "missed_winner_value": round(missed_v, 4),
        "net_filter_benefit": round(benefit, 4),
        "wins": kpi.get("wins"),
        "losses": kpi.get("losses"),
        "win_rate": kpi.get("win_rate"),
        "net": kpi.get("net_pnl"),
        "PF": kpi.get("profit_factor"),
        "avg_MFE": kpi.get("avg_mfe"),
        "median_MFE": kpi.get("median_mfe"),
        "avg_MAE": kpi.get("avg_mae"),
        "median_MAE": kpi.get("median_mae"),
        "early_dump_rate": kpi.get("early_dump_rate"),
        "early_dump_count": kpi.get("early_dump_count"),
        "fee_estimate_krw": fee_est,
        "fee_only_loss_count": kpi.get("fee_only_loss_count"),
        "outcome_labels": dict(labels),
    }


def fee_churn_feature_study(baseline_accepted: Sequence[ForwardObs]) -> dict[str, Any]:
    """Fee-churn 특성 — 미래 수익 기반 REAL filter 금지. 진입 feature만."""

    fee_churn = []
    for o in baseline_accepted:
        mfe = o.mfe_pct
        net = float(o.outcome.get("net_pnl_krw") or 0)
        gross = float(o.outcome.get("gross_pnl_krw") or 0)
        r60 = _feat_num(o.features, "return_60m")
        is_fc = (abs(gross) < 1e-9 and net < 0) or (
            mfe is not None and abs(mfe) < FEE_RT_PCT_THRESHOLD and net < 0
        )
        low_edge = r60 is not None and abs(r60) < FEE_RT_PCT_THRESHOLD * 2
        if is_fc or low_edge:
            fee_churn.append(o)

    def _dist(key_metric: str) -> dict[str, Any]:
        vals_fc: list[float] = []
        vals_other: list[float] = []
        fc_ids = {o.shadow_id for o in fee_churn}
        for o in baseline_accepted:
            if key_metric == "rsi14":
                v = o.metrics.rsi14
            elif key_metric == "ma_separation_pct":
                v = o.metrics.ma_separation_pct
            elif key_metric == "volume_surge":
                v = o.metrics.volume_surge
            elif key_metric.startswith("pre_") or key_metric.startswith("dist_"):
                v = _feat_num(o.features, key_metric)
            else:
                v = None
            if v is None:
                continue
            (vals_fc if o.shadow_id in fc_ids else vals_other).append(float(v))
        return {
            "fee_churn_n": len(vals_fc),
            "fee_churn_median": _median(vals_fc),
            "other_n": len(vals_other),
            "other_median": _median(vals_other),
        }

    return {
        "fee_rt_pct_threshold": FEE_RT_PCT_THRESHOLD,
        "fee_churn_or_low_edge_count": len(fee_churn),
        "baseline_n": len(baseline_accepted),
        "rate": (
            round(len(fee_churn) / len(baseline_accepted), 4)
            if baseline_accepted
            else None
        ),
        "feature_medians": {
            "rsi14": _dist("rsi14"),
            "ma_separation_pct": _dist("ma_separation_pct"),
            "volume_surge": _dist("volume_surge"),
            "pre_entry_return_5m": _dist("pre_entry_return_5m"),
            "dist_from_15m_high_pct": _dist("dist_from_15m_high_pct"),
        },
        "note": (
            "Entry-time features only — do NOT build REAL filter from "
            "post-entry MFE/60m movement"
        ),
    }


def _pick_best_two_filter(
    baseline_accepted: Sequence[ForwardObs],
    single_results: dict[str, dict[str, Any]],
) -> tuple[str, Callable[[ForwardObs], bool], str]:
    """E8 = best 2-filter by net_filter_benefit among E1–E5 pairs."""

    codes = ["E1", "E2", "E3", "E4", "E5"]
    best_code = "E6"
    best_benefit = float("-inf")
    best_fn = _combine(_pass_e1, _pass_e3)
    best_name = "E1+E3 (default)"

    for i, a in enumerate(codes):
        for b in codes[i + 1 :]:
            fn = _combine(FILTER_SPECS[a].accept_fn, FILTER_SPECS[b].accept_fn)
            arm = evaluate_filter_arm(
                baseline_accepted,
                code=f"E8_{a}_{b}",
                name_ko=f"{a}+{b}",
                accept_fn=fn,
            )
            ben = float(arm.get("net_filter_benefit") or 0)
            if ben > best_benefit:
                best_benefit = ben
                best_fn = fn
                best_code = f"E8_{a}_{b}"
                best_name = f"{FILTER_SPECS[a].name_ko} + {FILTER_SPECS[b].name_ko}"

    # Prefer published singles' benefit for tie-break logging
    _ = single_results
    return best_code, best_fn, best_name


def run_entry_quality_early_dump_experiment(rows: Sequence[Any]) -> dict[str, Any]:
    """COMPLETED shadow rows → CLEAN-only entry quality experiment."""

    partition = partition_forward_rows(rows)
    clean_obs = assign_clean_forward_obs(rows)
    clean_n = len(clean_obs)
    gate = sample_gate(clean_n)

    baseline_pool = [o for o in clean_obs if o.baseline_eligible]

    labels_all = Counter(outcome_label(o) for o in baseline_pool)

    # E0 baseline arm
    e0_kpi = arm_kpi(baseline_pool, eligible="baseline_eligible")
    e0 = {
        "code": "E0",
        "name_ko": "현재 REAL 진입 Baseline",
        "total_baseline_candidates": len(baseline_pool),
        "accepted": len(baseline_pool),
        "filtered": 0,
        "entry_count_reduction_pct": 0.0,
        "avoided_losers": 0,
        "avoided_loser_value": 0.0,
        "missed_winners": 0,
        "missed_winner_value": 0.0,
        "net_filter_benefit": 0.0,
        "wins": e0_kpi.get("wins"),
        "losses": e0_kpi.get("losses"),
        "win_rate": e0_kpi.get("win_rate"),
        "net": e0_kpi.get("net_pnl"),
        "PF": e0_kpi.get("profit_factor"),
        "avg_MFE": e0_kpi.get("avg_mfe"),
        "median_MFE": e0_kpi.get("median_mfe"),
        "avg_MAE": e0_kpi.get("avg_mae"),
        "median_MAE": e0_kpi.get("median_mae"),
        "early_dump_rate": e0_kpi.get("early_dump_rate"),
        "early_dump_count": e0_kpi.get("early_dump_count"),
        "fee_estimate_krw": round(
            sum(float(o.outcome.get("estimated_fee_krw") or 0) for o in baseline_pool),
            4,
        ),
        "fee_only_loss_count": e0_kpi.get("fee_only_loss_count"),
        "outcome_labels": dict(labels_all),
        "policy": {
            "rsi_max": ENTRY_BASELINE_SPEC.rsi_max,
            "min_volume_surge": ENTRY_BASELINE_SPEC.min_volume_surge,
            "min_ma_separation_pct": ENTRY_BASELINE_SPEC.min_ma_separation_pct,
            "exit": "TP10 / trail3 / SL5 (baseline exit — identical)",
        },
    }

    arms: dict[str, dict[str, Any]] = {"E0": e0}
    for code, spec in FILTER_SPECS.items():
        arms[code] = evaluate_filter_arm(
            baseline_pool,
            code=code,
            name_ko=spec.name_ko,
            accept_fn=spec.accept_fn,
        )
        arms[code]["description"] = spec.description

    # E6 / E7 fixed combos
    arms["E6"] = evaluate_filter_arm(
        baseline_pool,
        code="E6",
        name_ko="RSI 고점 + 스파이크 거부",
        accept_fn=_combine(_pass_e1, _pass_e3),
    )
    arms["E7"] = evaluate_filter_arm(
        baseline_pool,
        code="E7",
        name_ko="RSI 고점 + 고점 추격 거부",
        accept_fn=_combine(_pass_e1, _pass_e4),
    )

    # E8 only when enough for diagnostic
    if clean_n >= N_COLLECTION and baseline_pool:
        e8_code, e8_fn, e8_name = _pick_best_two_filter(baseline_pool, arms)
        arms["E8"] = evaluate_filter_arm(
            baseline_pool,
            code=e8_code,
            name_ko=f"최적 2필터: {e8_name}",
            accept_fn=e8_fn,
        )
        arms["E8"]["note"] = (
            "Best 2-filter by net_filter_benefit on CLEAN only — RESEARCH, not promotion"
        )
    else:
        arms["E8"] = {
            "code": "E8",
            "name_ko": "최적 2필터",
            "accepted": 0,
            "filtered": 0,
            "net_filter_benefit": None,
            "note": "INSUFFICIENT_SAMPLE for E8 selection",
            "skipped": True,
        }

    # Best among E1–E8 by net_filter_benefit (diagnostic)
    ranked = []
    for code, arm in arms.items():
        if code == "E0" or arm.get("skipped"):
            continue
        ranked.append(
            (
                float(arm.get("net_filter_benefit") or 0),
                code,
                arm.get("name_ko"),
                arm.get("accepted"),
            )
        )
    ranked.sort(reverse=True)
    best = ranked[0] if ranked else None

    fee_study = fee_churn_feature_study(baseline_pool)

    # Promotion — always NO until gates; never auto
    promo_failures: list[str] = []
    if clean_n < N_PRIMARY:
        promo_failures.append("CLEAN_N_LT_500")
    if gate in {GATE_COLLECTION, GATE_DIAGNOSTIC}:
        promo_failures.append(f"SAMPLE_GATE_{gate}")
    promo_failures.append("AUTO_PROMOTE_DISABLED")
    # Even if best filter looks good — require N>=500 and explicit review
    if best is not None:
        best_arm = arms.get(best[1]) or {}
        if float(best_arm.get("net") or 0) <= float(e0.get("net") or 0):
            promo_failures.append("BEST_NET_NOT_GT_BASELINE")
        if (best_arm.get("PF") or 0) <= (e0.get("PF") or 0):
            promo_failures.append("BEST_PF_NOT_GT_BASELINE")
        if (best_arm.get("early_dump_rate") or 1) >= (e0.get("early_dump_rate") or 0):
            promo_failures.append("EARLY_DUMP_NOT_IMPROVED")
        if float(best_arm.get("net_filter_benefit") or 0) <= 0:
            promo_failures.append("NET_FILTER_BENEFIT_LE_0")
        red = best_arm.get("entry_count_reduction_pct")
        if red is not None and float(red) > 50:
            promo_failures.append("ENTRY_REDUCTION_GT_50PCT")

    feature_coverage = {
        "pre_entry_return_5m": sum(
            1
            for o in baseline_pool
            if _feat_num(o.features, "pre_entry_return_5m") is not None
        ),
        "dist_from_15m_high_pct": sum(
            1
            for o in baseline_pool
            if _feat_num(o.features, "dist_from_15m_high_pct") is not None
        ),
        "rsi14": sum(1 for o in baseline_pool if o.metrics.rsi14 is not None),
        "volume_surge": sum(
            1 for o in baseline_pool if o.metrics.volume_surge is not None
        ),
    }

    if gate == GATE_COLLECTION:
        verdict = "COLLECTION_ONLY"
        next_action = "COLLECT_MORE_CLEAN_FORWARD"
    elif gate == GATE_DIAGNOSTIC:
        verdict = "DIAGNOSTIC_ONLY"
        next_action = "COLLECT_MORE_CLEAN_FORWARD"
    elif gate == GATE_PRIMARY:
        verdict = "PRIMARY_REVIEW_READY"
        next_action = "REVIEW_ENTRY_FILTER_AFTER_500_CLEAN"
    else:
        verdict = "RECOMMENDED_REVIEW_READY"
        next_action = "REVIEW_ENTRY_FILTER_AFTER_500_CLEAN"

    return {
        "schema": "entry_quality_early_dump_experiment_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "FINAL_VERDICT": verdict,
        "SAMPLE_GATE": gate,
        "CLEAN_SAMPLE_COUNT": clean_n,
        "CLEAN_BASELINE_ENTRIES": len(baseline_pool),
        "TARGET_PROGRESS_500": f"{clean_n} / {N_PRIMARY}",
        "TARGET_PROGRESS_1000": f"{clean_n} / {N_RECOMMENDED}",
        "progress_ratio_500": round(clean_n / N_PRIMARY, 4) if N_PRIMARY else 0,
        "progress_ratio_1000": (
            round(clean_n / N_RECOMMENDED, 4) if N_RECOMMENDED else 0
        ),
        "cohort_partition": {
            "LEGACY": partition.get("legacy_total"),
            "BACKFILL_STAMPED": partition.get("new_stamped_count"),
            "CLEAN_FORWARD": partition.get("clean_new_count"),
            "excluded_invalid_price": partition.get("excluded_invalid_price"),
            "excluded_time_alignment": partition.get("excluded_time_alignment"),
            "clean_epoch_start": partition.get("clean_epoch_start"),
        },
        "BASELINE": e0,
        "filters": arms,
        "BEST_FILTER_CURRENTLY": (
            {
                "code": best[1],
                "name_ko": best[2],
                "net_filter_benefit": best[0],
                "accepted": best[3],
            }
            if best
            else None
        ),
        "BEST_FILTER_SAMPLE_SIZE": clean_n,
        "FEE_CHURN_FINDINGS": fee_study,
        "REAL_14_REFERENCE": REAL_14_REFERENCE,
        "outcome_label_counts_baseline": dict(labels_all),
        "feature_coverage": feature_coverage,
        "REAL_PROMOTION_RECOMMENDED": "NO",
        "PROMOTION_GATE_FAILURES": promo_failures,
        "AUTO_PROMOTE": False,
        "SYSTEM_BUG_ACTIVE": "NO",
        "mutations": {
            "REAL_ORDER_MUTATION": 0,
            "REAL_POLICY_MUTATION": 0,
            "EXIT_POLICY_MUTATION": 0,
            "RISK_MUTATION": 0,
            "SLOT_POLICY_MUTATION": 0,
            "LIVE_ARM_MUTATION": 0,
            "UBA1381_MUTATION": 0,
        },
        "NEXT_ACTION": next_action,
        "dashboard": {
            "title_ko": "진입 품질 Early-Dump 필터 실험 (CLEAN)",
            "clean_progress_500": f"{clean_n} / {N_PRIMARY}",
            "clean_progress_1000": f"{clean_n} / {N_RECOMMENDED}",
            "sample_gate": gate,
            "baseline_net": e0.get("net"),
            "baseline_pf": e0.get("PF"),
            "baseline_early_dump": e0.get("early_dump_rate"),
            "best_filter": best[1] if best else None,
            "best_benefit": best[0] if best else None,
            "real_reference": REAL_14_REFERENCE,
            "legacy_note": "이전 연구 결과 (참고용) — 승격 제외",
            "filters_summary": [
                {
                    "code": a["code"],
                    "name_ko": a.get("name_ko"),
                    "accepted": a.get("accepted"),
                    "win_rate": a.get("win_rate"),
                    "net": a.get("net"),
                    "PF": a.get("PF"),
                    "early_dump_rate": a.get("early_dump_rate"),
                    "avoided_losers": a.get("avoided_losers"),
                    "missed_winners": a.get("missed_winners"),
                    "net_filter_benefit": a.get("net_filter_benefit"),
                }
                for a in arms.values()
                if not a.get("skipped")
            ],
        },
    }


def summarize_entry_quality_experiment_from_shadows(
    rows: Sequence[Any],
) -> dict[str, Any]:
    """stats.py fail-open wrapper."""

    try:
        return run_entry_quality_early_dump_experiment(rows)
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "entry_quality_early_dump_experiment_v1",
            "FINAL_VERDICT": "ERROR",
            "error": str(exc)[:200],
            "CLEAN_SAMPLE_COUNT": 0,
            "REAL_PROMOTION_RECOMMENDED": "NO",
            "AUTO_PROMOTE": False,
            "mutations": {
                "REAL_ORDER_MUTATION": 0,
                "REAL_POLICY_MUTATION": 0,
                "EXIT_POLICY_MUTATION": 0,
                "RISK_MUTATION": 0,
                "SLOT_POLICY_MUTATION": 0,
                "LIVE_ARM_MUTATION": 0,
                "UBA1381_MUTATION": 0,
            },
        }
