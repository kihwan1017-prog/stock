"""Entry Candidate 최종 승격 리뷰 — Baseline vs B1(RSI65) vs B(RSI65+VOL1.0).

READ/SHADOW ONLY. REAL 정책·주문 변경 금지.
Exit는 항상 TP10/trail3 baseline.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Sequence

from stock_platform.operation.upbit_opportunity_shadow.entry_policy_ab import (
    ENTRY_BASELINE_SPEC,
    ENTRY_CANDIDATE_B_SPEC,
    ENTRY_RSI65_ONLY_SPEC,
    OpportunityMetrics,
    baseline_exit_outcome,
    evaluate_entry_eligibility,
    metrics_from_shadow_row,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_policy_ab import (
    _arm_kpis,
)

LABEL_BASELINE = "BASELINE"
LABEL_B1 = "CANDIDATE_B1_RSI65_VOL08"
LABEL_B = "CANDIDATE_B_RSI65_VOL10"

PREFERRED_B1 = "RSI65_VOL08"
PREFERRED_B = "RSI65_VOL10"

VERDICT_B1_NOT_PROFITABLE = "ENTRY_RSI65_VOL08_PREFERRED_BUT_NOT_PROFITABLE"
VERDICT_B_NOT_PROFITABLE = "ENTRY_RSI65_VOL10_PREFERRED_BUT_NOT_PROFITABLE"
VERDICT_READY = "ENTRY_CANDIDATE_READY_FOR_REAL_PROMOTION"
VERDICT_NOT_STABLE = "ENTRY_CANDIDATES_NOT_STABLE"

NEXT_COLLECT = "COLLECT_MORE_FORWARD_SAMPLE_WITH_PREFERRED_ENTRY_CANDIDATE"
NEXT_REVIEW = "REVIEW_PREFERRED_ENTRY_CANDIDATE_FOR_REAL_PROMOTION"


@dataclass(frozen=True, slots=True)
class ObsRow:
    """동일 opportunity 관측."""

    shadow_id: int
    symbol: str
    detected_at: Any
    metrics: OpportunityMetrics
    outcome: dict[str, Any]
    mfe_pct: float | None
    mae_pct: float | None
    baseline_eligible: bool
    b1_eligible: bool
    b_eligible: bool


def build_obs_from_shadow(row: Any) -> ObsRow | None:
    outcome = baseline_exit_outcome(row)
    if outcome is None:
        return None
    metrics = metrics_from_shadow_row(row)
    b_ok, _ = evaluate_entry_eligibility(metrics, ENTRY_BASELINE_SPEC)
    b1_ok, _ = evaluate_entry_eligibility(metrics, ENTRY_RSI65_ONLY_SPEC)
    bb_ok, _ = evaluate_entry_eligibility(metrics, ENTRY_CANDIDATE_B_SPEC)
    return ObsRow(
        shadow_id=int(getattr(row, "shadow_id", 0) or 0),
        symbol=str(getattr(row, "symbol", "") or ""),
        detected_at=getattr(row, "detected_at", None),
        metrics=metrics,
        outcome=dict(outcome),
        mfe_pct=(
            float(row.mfe_pct)
            if getattr(row, "mfe_pct", None) is not None
            else None
        ),
        mae_pct=(
            float(row.mae_pct)
            if getattr(row, "mae_pct", None) is not None
            else None
        ),
        baseline_eligible=b_ok,
        b1_eligible=b1_ok,
        b_eligible=bb_ok,
    )


def _eligible_outcomes(
    rows: Sequence[ObsRow], *, key: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        ok = getattr(r, key)
        if ok:
            out.append(r.outcome)
    return out


def _avg(vals: Sequence[float]) -> float | None:
    if not vals:
        return None
    return round(sum(vals) / len(vals), 6)


def arm_summary(
    rows: Sequence[ObsRow],
    *,
    eligible_attr: str,
    label: str,
    vs_baseline_attr: str | None = None,
) -> dict[str, Any]:
    """정책 arm KPI + (옵션) Baseline 대비 filter quality."""

    outs = _eligible_outcomes(rows, key=eligible_attr)
    kpi = _arm_kpis(outs)
    mfe = _avg(
        [
            float(r.mfe_pct)
            for r in rows
            if getattr(r, eligible_attr) and r.mfe_pct is not None
        ]
    )
    mae = _avg(
        [
            float(r.mae_pct)
            for r in rows
            if getattr(r, eligible_attr) and r.mae_pct is not None
        ]
    )
    n = int(kpi.get("sample_count") or 0)
    net = float(kpi.get("net_pnl") or 0.0)
    pf = kpi.get("profit_factor")
    absolute_net_profitable = net > 0
    pf_above_1 = pf is not None and float(pf) > 1.0

    filter_q: dict[str, Any] | None = None
    if vs_baseline_attr is not None:
        filter_q = filter_quality_vs_baseline(
            rows,
            baseline_attr=vs_baseline_attr,
            candidate_attr=eligible_attr,
        )

    return {
        "label": label,
        "entries": n,
        "wins": kpi.get("wins"),
        "losses": kpi.get("losses"),
        "win_rate": kpi.get("win_rate"),
        "gross_pnl": kpi.get("gross_pnl"),
        "fees": kpi.get("fees"),
        "net_pnl": kpi.get("net_pnl"),
        "avg_return": kpi.get("avg_return"),
        "median_return": kpi.get("median_return"),
        "profit_factor": pf,
        "max_drawdown_proxy": kpi.get("max_drawdown_proxy"),
        "max_single_loss": kpi.get("max_trade_loss"),
        "avg_mfe_pct": mfe,
        "avg_mae_pct": mae,
        "avg_holding_seconds": kpi.get("avg_holding_seconds"),
        "fee_churn_count": kpi.get("fee_only_loss_count"),
        "ABSOLUTE_NET_PROFITABLE": "YES" if absolute_net_profitable else "NO",
        "PROFIT_FACTOR_ABOVE_1": "YES" if pf_above_1 else "NO",
        "IMPROVED_BUT_NOT_PROFITABLE": (
            not absolute_net_profitable or not pf_above_1
        ),
        "filter_vs_baseline": filter_q,
    }


def filter_quality_vs_baseline(
    rows: Sequence[ObsRow],
    *,
    baseline_attr: str,
    candidate_attr: str,
) -> dict[str, Any]:
    """Baseline 통과 · Candidate 차단 → avoided loser / missed winner."""

    missed = 0
    avoided = 0
    missed_net = 0.0
    avoided_net = 0.0
    for r in rows:
        if not getattr(r, baseline_attr):
            continue
        if getattr(r, candidate_attr):
            continue
        net = float(r.outcome.get("net_pnl_krw") or 0.0)
        if net > 0:
            missed += 1
            missed_net += net
        elif net < 0:
            avoided += 1
            avoided_net += net
    avoided_value = abs(avoided_net)
    missed_value = missed_net
    return {
        "avoided_loser_count": avoided,
        "avoided_loser_value": round(avoided_value, 4),
        "missed_winner_count": missed,
        "missed_winner_value": round(missed_value, 4),
        "net_filter_benefit": round(avoided_value - missed_value, 4),
    }


def time_split_stability(rows: Sequence[ObsRow]) -> dict[str, Any]:
    """detected_at 시간순 early/middle/late 1/3."""

    ordered = sorted(
        [r for r in rows if r.detected_at is not None],
        key=lambda r: r.detected_at,
    )
    n = len(ordered)
    if n < 3:
        return {"status": "INSUFFICIENT_FOR_SPLIT", "n": n}

    a = n // 3
    b = 2 * n // 3
    chunks = {
        "early": ordered[:a],
        "middle": ordered[a:b],
        "late": ordered[b:],
    }
    out: dict[str, Any] = {"n_total": n, "chunk_sizes": {}}
    for name, chunk in chunks.items():
        out["chunk_sizes"][name] = len(chunk)
        out[name] = {
            "baseline": _thin_arm(chunk, "baseline_eligible"),
            "b1": _thin_arm(chunk, "b1_eligible"),
            "b": _thin_arm(chunk, "b_eligible"),
        }
    # 각 구간에서 B1/B가 Baseline보다 net 나은지
    direction = []
    for name in ("early", "middle", "late"):
        sec = out[name]
        b_net = float(sec["baseline"]["net_pnl"] or 0)
        b1_net = float(sec["b1"]["net_pnl"] or 0)
        bb_net = float(sec["b"]["net_pnl"] or 0)
        direction.append(
            {
                "chunk": name,
                "b1_better_than_baseline": b1_net > b_net,
                "b_better_than_baseline": bb_net > b_net,
                "b1_better_than_b": b1_net > bb_net,
            }
        )
    out["direction_checks"] = direction
    out["b1_beats_baseline_all_chunks"] = all(
        d["b1_better_than_baseline"] for d in direction
    )
    out["b_beats_baseline_all_chunks"] = all(
        d["b_better_than_baseline"] for d in direction
    )
    return out


def _thin_arm(rows: Sequence[ObsRow], attr: str) -> dict[str, Any]:
    kpi = _arm_kpis(_eligible_outcomes(rows, key=attr))
    return {
        "entries": kpi.get("sample_count"),
        "net_pnl": kpi.get("net_pnl"),
        "profit_factor": kpi.get("profit_factor"),
        "win_rate": kpi.get("win_rate"),
    }


def bootstrap_stability(
    rows: Sequence[ObsRow],
    *,
    n_resamples: int = 200,
    seed: int = 42,
) -> dict[str, Any]:
    """동일 크기 복원추출 — B1/B가 Baseline보다 net 우위인 비율."""

    if len(rows) < 30:
        return {"status": "INSUFFICIENT", "n": len(rows)}
    rng = random.Random(seed)
    b1_win = 0
    b_win = 0
    b1_vs_b = 0
    for _ in range(n_resamples):
        sample = [rows[rng.randrange(len(rows))] for _ in range(len(rows))]
        base = float(
            _arm_kpis(_eligible_outcomes(sample, key="baseline_eligible")).get(
                "net_pnl"
            )
            or 0
        )
        b1 = float(
            _arm_kpis(_eligible_outcomes(sample, key="b1_eligible")).get(
                "net_pnl"
            )
            or 0
        )
        bb = float(
            _arm_kpis(_eligible_outcomes(sample, key="b_eligible")).get(
                "net_pnl"
            )
            or 0
        )
        if b1 > base:
            b1_win += 1
        if bb > base:
            b_win += 1
        if b1 > bb:
            b1_vs_b += 1
    return {
        "n_resamples": n_resamples,
        "b1_beats_baseline_rate": round(b1_win / n_resamples, 4),
        "b_beats_baseline_rate": round(b_win / n_resamples, 4),
        "b1_beats_b_rate": round(b1_vs_b / n_resamples, 4),
        "stable_threshold": 0.70,
        "b1_stable_vs_baseline": (b1_win / n_resamples) >= 0.70,
        "b_stable_vs_baseline": (b_win / n_resamples) >= 0.70,
    }


def _score_tuple(arm: dict[str, Any]) -> tuple:
    """승격 우선순위 튜플 (클수록 선호)."""

    net = float(arm.get("net_pnl") or 0)
    pf = arm.get("profit_factor")
    pf_v = float(pf) if pf is not None else -999.0
    filt = (arm.get("filter_vs_baseline") or {}).get("net_filter_benefit")
    filt_v = float(filt) if filt is not None else 0.0
    max_loss = float(arm.get("max_single_loss") or 0)  # less negative better
    fees = -float(arm.get("fees") or 0)  # lower fees better → negate
    entries = float(arm.get("entries") or 0)
    return (net, pf_v, filt_v, max_loss, fees, entries)


def decide_promotion(
    *,
    baseline: dict[str, Any],
    b1: dict[str, Any],
    b: dict[str, Any],
    stability: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """PREFERRED + ABSOLUTE profitability + REAL 추천 여부."""

    # 안정성: time-split 또는 bootstrap 실패 시 NOT_STABLE
    b1_stable = bool(
        stability.get("b1_beats_baseline_all_chunks")
    ) or bool(bootstrap.get("b1_stable_vs_baseline"))
    b_stable = bool(stability.get("b_beats_baseline_all_chunks")) or bool(
        bootstrap.get("b_stable_vs_baseline")
    )

    # Baseline 대비 개선 여부
    b1_better = float(b1.get("net_pnl") or 0) > float(
        baseline.get("net_pnl") or 0
    )
    b_better = float(b.get("net_pnl") or 0) > float(
        baseline.get("net_pnl") or 0
    )

    if not b1_better and not b_better:
        return {
            "PREFERRED_ENTRY_CANDIDATE": None,
            "FINAL_VERDICT": VERDICT_NOT_STABLE,
            "REAL_PROMOTION_RECOMMENDED": "NO",
            "NEXT_ACTION": NEXT_COLLECT,
            "reason": "NEITHER_IMPROVES_NET_VS_BASELINE",
        }

    # B1 vs B: 우선순위 튜플 (Net > PF > filter benefit > max loss > fee > frequency)
    prefer_b1 = _score_tuple(b1) >= _score_tuple(b)
    preferred = PREFERRED_B1 if prefer_b1 else PREFERRED_B
    chosen = b1 if prefer_b1 else b
    chosen_stable = b1_stable if prefer_b1 else b_stable

    rate_key = (
        "b1_beats_baseline_rate" if prefer_b1 else "b_beats_baseline_rate"
    )
    rate = float(bootstrap.get(rate_key) or 0)
    chunk_ok = bool(
        stability.get("b1_beats_baseline_all_chunks")
        if prefer_b1
        else stability.get("b_beats_baseline_all_chunks")
    )
    if not chosen_stable and not chunk_ok and rate < 0.60:
        return {
            "PREFERRED_ENTRY_CANDIDATE": preferred,
            "FINAL_VERDICT": VERDICT_NOT_STABLE,
            "REAL_PROMOTION_RECOMMENDED": "NO",
            "NEXT_ACTION": NEXT_COLLECT,
            "reason": "UNSTABLE_ACROSS_TIME_OR_BOOTSTRAP",
            "bootstrap_rate": rate,
        }

    abs_ok = chosen.get("ABSOLUTE_NET_PROFITABLE") == "YES"
    pf_ok = chosen.get("PROFIT_FACTOR_ABOVE_1") == "YES"

    if abs_ok and pf_ok:
        return {
            "PREFERRED_ENTRY_CANDIDATE": preferred,
            "FINAL_VERDICT": VERDICT_READY,
            "REAL_PROMOTION_RECOMMENDED": "YES",
            "NEXT_ACTION": NEXT_REVIEW,
            "ABSOLUTE_NET_PROFITABLE": "YES",
            "PROFIT_FACTOR_ABOVE_1": "YES",
            "reason": "ABSOLUTE_PROFITABILITY_CONFIRMED",
        }

    verdict = (
        VERDICT_B1_NOT_PROFITABLE if prefer_b1 else VERDICT_B_NOT_PROFITABLE
    )
    return {
        "PREFERRED_ENTRY_CANDIDATE": preferred,
        "FINAL_VERDICT": verdict,
        "REAL_PROMOTION_RECOMMENDED": "NO",
        "NEXT_ACTION": NEXT_COLLECT,
        "ABSOLUTE_NET_PROFITABLE": "YES" if abs_ok else "NO",
        "PROFIT_FACTOR_ABOVE_1": "YES" if pf_ok else "NO",
        "classification": "IMPROVED_BUT_NOT_PROFITABLE",
        "reason": "BETTER_THAN_BASELINE_BUT_STILL_NEGATIVE_OR_PF_LT_1",
    }


def run_final_promotion_review(rows: Sequence[Any]) -> dict[str, Any]:
    """COMPLETED shadow rows → 최종 승격 리뷰."""

    obs: list[ObsRow] = []
    for row in rows:
        item = build_obs_from_shadow(row)
        if item is not None:
            obs.append(item)

    baseline = arm_summary(
        obs, eligible_attr="baseline_eligible", label=LABEL_BASELINE
    )
    b1 = arm_summary(
        obs,
        eligible_attr="b1_eligible",
        label=LABEL_B1,
        vs_baseline_attr="baseline_eligible",
    )
    b = arm_summary(
        obs,
        eligible_attr="b_eligible",
        label=LABEL_B,
        vs_baseline_attr="baseline_eligible",
    )

    base_n = int(baseline.get("entries") or 0)
    b1_n = int(b1.get("entries") or 0)
    b_n = int(b.get("entries") or 0)

    stability = time_split_stability(obs)
    bootstrap = bootstrap_stability(obs)
    decision = decide_promotion(
        baseline=baseline,
        b1=b1,
        b=b,
        stability=stability,
        bootstrap=bootstrap,
    )

    b1_vs_b = {
        "net_difference": round(
            float(b1.get("net_pnl") or 0) - float(b.get("net_pnl") or 0), 4
        ),
        "PF_difference": (
            None
            if b1.get("profit_factor") is None or b.get("profit_factor") is None
            else round(
                float(b1["profit_factor"]) - float(b["profit_factor"]), 6
            )
        ),
        "trade_frequency_difference": b1_n - b_n,
        "b1_reduction_vs_baseline_pct": (
            round((1 - b1_n / base_n) * 100, 2) if base_n else None
        ),
        "b_reduction_vs_baseline_pct": (
            round((1 - b_n / base_n) * 100, 2) if base_n else None
        ),
        "filter_benefit_difference": round(
            float((b1.get("filter_vs_baseline") or {}).get("net_filter_benefit") or 0)
            - float((b.get("filter_vs_baseline") or {}).get("net_filter_benefit") or 0),
            4,
        ),
    }

    return {
        "sample_count": len(obs),
        "policies": {
            "baseline": {
                "rsi_max": ENTRY_BASELINE_SPEC.rsi_max,
                "min_volume_surge": ENTRY_BASELINE_SPEC.min_volume_surge,
            },
            "b1": {
                "rsi_max": ENTRY_RSI65_ONLY_SPEC.rsi_max,
                "min_volume_surge": ENTRY_RSI65_ONLY_SPEC.min_volume_surge,
            },
            "b": {
                "rsi_max": ENTRY_CANDIDATE_B_SPEC.rsi_max,
                "min_volume_surge": ENTRY_CANDIDATE_B_SPEC.min_volume_surge,
            },
            "exit": "TP10 / trail3 / MA anti-churn identical",
        },
        "baseline": baseline,
        "candidate_b1": b1,
        "candidate_b": b,
        "b1_vs_b": b1_vs_b,
        "stability_time_split": stability,
        "stability_bootstrap": bootstrap,
        **decision,
        "REAL_policy_changed": "NO",
        "real_order": False,
        "candidate_a_exit_unused": True,
    }
