"""Entry Candidate B1 Forward Validation — Baseline vs B1 (Shadow only).

REAL Entry/Exit/Risk/Slot 정책 변경·자동 승격 금지.
LEGACY_FORWARD(459) 보존 + NEW_UNSEEN_FORWARD 분리.
Exit는 항상 TP10/trail3 baseline (Candidate A 미사용).
Volume>=1.0 Candidate B는 연구 대상에서 제외.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from stock_platform.operation.upbit_opportunity_shadow.entry_policy_ab import (
    ENTRY_BASELINE_SPEC,
    ENTRY_RSI65_ONLY_SPEC,
    OpportunityMetrics,
    baseline_exit_outcome,
    evaluate_entry_eligibility,
    is_early_dump_proxy,
    metrics_from_shadow_row,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_policy_ab import (
    BASELINE_SPEC as EXIT_BASELINE_SPEC,
    _arm_kpis,
)

KST = ZoneInfo("Asia/Seoul")

# ── 표본 SoT (기존 promotion review 459건 고정) ─────────────────────────────
LEGACY_FORWARD_COUNT = 459
TARGET_COMBINED_OPPORTUNITIES = 1000
TARGET_NEW_UNSEEN = 500

COHORT_LEGACY = "LEGACY_FORWARD"
COHORT_NEW = "NEW_UNSEEN_FORWARD"

LABEL_BASELINE = "ENTRY_BASELINE"
LABEL_B1 = "ENTRY_CANDIDATE_B1_RSI65_VOL08"

# B1 = RSI65 + VOL0.8 (Candidate B VOL1.0 제외)
ENTRY_CANDIDATE_B1_SPEC = ENTRY_RSI65_ONLY_SPEC

VERDICT_COLLECTING = "SAMPLE_COLLECTION_IN_PROGRESS"
VERDICT_GATES_FAILED = "B1_PROMOTION_GATES_FAILED"
VERDICT_REVIEW_READY = "B1_REVIEW_READY_NOT_AUTO_PROMOTED"

NEXT_COLLECT = "COLLECT_MORE_NEW_UNSEEN_FORWARD"
NEXT_REVIEW_FAIL = "REVIEW_FAILED_PROMOTION_GATES_WITH_CHATGPT"
NEXT_REVIEW_PASS = "REVIEW_B1_REAL_PROMOTION_WITH_CHATGPT"

# Early dump SoT: entry_policy_ab.is_early_dump_proxy (return_5m<=-0.3 등)
EARLY_DUMP_DEFINITION = (
    "SoT: is_early_dump_proxy — return_5m_pct<=-0.3 or window5<=-0.3 "
    "or (hold<=180s and mae<=-0.5)"
)

# symbol concentration: top1 net share of positive B1 net (if any)
SYMBOL_CONCENTRATION_MAX_SHARE = 0.50


@dataclass(frozen=True, slots=True)
class ForwardObs:
    """동일 opportunity Baseline/B1 관측."""

    shadow_id: int
    symbol: str
    detected_at: datetime | None
    cohort: str
    metrics: OpportunityMetrics
    outcome: dict[str, Any]
    mfe_pct: float | None
    mae_pct: float | None
    baseline_eligible: bool
    b1_eligible: bool
    early_dump: bool
    features: dict[str, Any]


def _avg(vals: Sequence[float]) -> float | None:
    if not vals:
        return None
    return round(sum(vals) / len(vals), 6)


def _median(vals: Sequence[float]) -> float | None:
    if not vals:
        return None
    return float(statistics.median(vals))


def _as_utc(dt: Any) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def extract_forward_features(row: Any) -> dict[str, Any]:
    """저장 가능한 feature — 없으면 NOT_AVAILABLE.

    evaluator가 evaluation_detail.entry_forward_features 를 stamp하면 우선 사용.
    """

    detail = getattr(row, "evaluation_detail", None) or {}
    stamped = detail.get("entry_forward_features") if isinstance(detail, dict) else None
    if isinstance(stamped, dict) and stamped:
        return dict(stamped)

    snap = getattr(row, "entry_snapshot", None) or {}
    cand = snap.get("candidate") if isinstance(snap, dict) else {}
    cand = cand if isinstance(cand, dict) else {}
    windows = detail.get("windows") if isinstance(detail, dict) else {}
    windows = windows if isinstance(windows, dict) else {}

    def _win_ret(key: str) -> float | None:
        w = windows.get(key) or {}
        if not isinstance(w, dict):
            return None
        v = w.get("return_pct")
        return float(v) if v is not None else None

    short = getattr(row, "ma5", None)
    long = getattr(row, "ma20", None)
    sep = cand.get("ma_spread_pct")
    if sep is None and short is not None and long is not None and float(long) != 0:
        sep = (float(short) - float(long)) / float(long) * 100.0

    return {
        "timestamp": (
            _as_utc(getattr(row, "detected_at", None)).isoformat()
            if getattr(row, "detected_at", None)
            else None
        ),
        "symbol": getattr(row, "symbol", None),
        "scanner_rank": getattr(row, "scanner_rank", None),
        "scanner_score": getattr(row, "scanner_score", None),
        "ai_recommendation": getattr(row, "recommendation", None),
        "ai_confidence": getattr(row, "confidence", None),
        "price": (
            float(row.entry_price)
            if getattr(row, "entry_price", None) is not None
            else None
        ),
        "ma_short": float(short) if short is not None else None,
        "ma_long": float(long) if long is not None else None,
        "ma_separation_pct": float(sep) if sep is not None else None,
        "rsi14": (
            float(row.rsi14) if getattr(row, "rsi14", None) is not None else None
        ),
        "volume_surge": (
            float(row.volume_surge)
            if getattr(row, "volume_surge", None) is not None
            else None
        ),
        "candidate_age": cand.get("candidate_age") or "NOT_AVAILABLE",
        "slot_assigned": cand.get("slot_assigned") or "NOT_AVAILABLE",
        "return_1m": _win_ret("1") if "1" in windows else "NOT_AVAILABLE",
        "return_3m": _win_ret("3") if "3" in windows else "NOT_AVAILABLE",
        "return_5m": (
            float(row.return_5m_pct)
            if getattr(row, "return_5m_pct", None) is not None
            else _win_ret("5")
        ),
        "return_10m": _win_ret("10") if "10" in windows else "NOT_AVAILABLE",
        "return_15m": (
            float(row.return_15m_pct)
            if getattr(row, "return_15m_pct", None) is not None
            else _win_ret("15")
        ),
        "return_30m": (
            float(row.return_30m_pct)
            if getattr(row, "return_30m_pct", None) is not None
            else _win_ret("30")
        ),
        "return_60m": (
            float(row.return_60m_pct)
            if getattr(row, "return_60m_pct", None) is not None
            else _win_ret("60")
        ),
        "pre_entry_return_1m": "NOT_AVAILABLE",
        "pre_entry_return_3m": "NOT_AVAILABLE",
        "pre_entry_return_5m": "NOT_AVAILABLE",
        "pre_entry_return_10m": "NOT_AVAILABLE",
        "dist_from_5m_high_pct": "NOT_AVAILABLE",
        "dist_from_15m_high_pct": "NOT_AVAILABLE",
        "dist_from_30m_high_pct": "NOT_AVAILABLE",
        "dist_from_60m_high_pct": "NOT_AVAILABLE",
        "recent_volatility": "NOT_AVAILABLE",
        "volume_acceleration": "NOT_AVAILABLE",
        "ma_slope": "NOT_AVAILABLE",
        "short_ma_slope": "NOT_AVAILABLE",
        "long_ma_slope": "NOT_AVAILABLE",
    }


def build_forward_obs(row: Any, *, cohort: str) -> ForwardObs | None:
    outcome = baseline_exit_outcome(row)
    if outcome is None:
        # evaluation_detail에 직접 exit_ab가 없을 수 있음 — entry_ab.outcome 폴백
        detail = getattr(row, "evaluation_detail", None) or {}
        if isinstance(detail, dict):
            entry_ab = detail.get("entry_ab") or {}
            if isinstance(entry_ab, dict) and isinstance(entry_ab.get("outcome"), dict):
                outcome = dict(entry_ab["outcome"])
    if outcome is None:
        return None

    metrics = metrics_from_shadow_row(row)
    b_ok, _ = evaluate_entry_eligibility(metrics, ENTRY_BASELINE_SPEC)
    b1_ok, _ = evaluate_entry_eligibility(metrics, ENTRY_CANDIDATE_B1_SPEC)
    return ForwardObs(
        shadow_id=int(getattr(row, "shadow_id", 0) or 0),
        symbol=str(getattr(row, "symbol", "") or ""),
        detected_at=_as_utc(getattr(row, "detected_at", None)),
        cohort=cohort,
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
        early_dump=is_early_dump_proxy(row),
        features=extract_forward_features(row),
    )


def assign_cohorts(rows: Sequence[Any]) -> list[ForwardObs]:
    """detected_at 순 정렬 후 최초 459 = LEGACY, 이후 = NEW.

    기존 evidence JSON은 수정하지 않는다 — count 경계만 SoT.
    """

    raw: list[tuple[datetime, int, Any]] = []
    for row in rows:
        # exit outcome 없는 row는 스킵
        probe = build_forward_obs(row, cohort=COHORT_LEGACY)
        if probe is None:
            continue
        dt = probe.detected_at or datetime.min.replace(tzinfo=timezone.utc)
        raw.append((dt, probe.shadow_id, row))
    raw.sort(key=lambda x: (x[0], x[1]))

    out: list[ForwardObs] = []
    for idx, (_dt, _sid, row) in enumerate(raw):
        cohort = COHORT_LEGACY if idx < LEGACY_FORWARD_COUNT else COHORT_NEW
        obs = build_forward_obs(row, cohort=cohort)
        if obs is not None:
            out.append(obs)
    return out


def arm_kpi(obs_list: Sequence[ForwardObs], *, eligible: str) -> dict[str, Any]:
    subset = [o for o in obs_list if getattr(o, eligible)]
    outs = [o.outcome for o in subset]
    kpi = _arm_kpis(outs)
    nets = [float(o.outcome.get("net_pnl_krw") or 0) for o in subset]
    wins = sum(1 for n in nets if n > 0)
    losses = sum(1 for n in nets if n < 0)
    fee_only = sum(
        1
        for o in subset
        if abs(float(o.outcome.get("gross_pnl_krw") or 0)) < 1e-9
        and float(o.outcome.get("net_pnl_krw") or 0) < 0
    )
    early_n = sum(1 for o in subset if o.early_dump)
    mfe = [float(o.mfe_pct) for o in subset if o.mfe_pct is not None]
    mae = [float(o.mae_pct) for o in subset if o.mae_pct is not None]
    return {
        **kpi,
        "opportunities": len(obs_list),
        "entries": len(subset),
        "filtered": len(obs_list) - len(subset),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(subset), 4) if subset else None,
        "average_net": _avg(nets),
        "median_net": _median(nets),
        "max_loss": min(nets) if nets else None,
        "avg_mfe": _avg(mfe),
        "median_mfe": _median(mfe),
        "avg_mae": _avg(mae),
        "median_mae": _median(mae),
        "fee_only_loss_count": fee_only,
        "early_dump_count": early_n,
        "early_dump_rate": round(early_n / len(subset), 4) if subset else None,
    }


def filter_attribution(obs_list: Sequence[ForwardObs]) -> dict[str, Any]:
    """Baseline pass · B1 fail → avoided losers / missed winners."""

    missed: list[dict[str, Any]] = []
    avoided: list[dict[str, Any]] = []
    for o in obs_list:
        if not o.baseline_eligible or o.b1_eligible:
            continue
        net = float(o.outcome.get("net_pnl_krw") or 0)
        row = {
            "symbol": o.symbol,
            "shadow_id": o.shadow_id,
            "rsi14": o.metrics.rsi14,
            "volume_surge": o.metrics.volume_surge,
            "net_pnl_krw": net,
            "early_dump": o.early_dump,
            "cohort": o.cohort,
        }
        if net > 0:
            missed.append(row)
        elif net < 0:
            avoided.append(row)
    missed_v = sum(float(x["net_pnl_krw"]) for x in missed)
    avoided_v = abs(sum(float(x["net_pnl_krw"]) for x in avoided))
    return {
        "avoided_losers": len(avoided),
        "avoided_loser_value": round(avoided_v, 4),
        "missed_winners": len(missed),
        "missed_winner_value": round(missed_v, 4),
        "net_filter_benefit": round(avoided_v - missed_v, 4),
        "missed_winners_sample": missed[:10],
        "avoided_losers_sample": avoided[:10],
    }


def rsi_65_70_band(obs_list: Sequence[ForwardObs]) -> dict[str, Any]:
    """Baseline 통과 · RSI (65, 70] — B1이 걸러내는 영역."""

    band = [
        o
        for o in obs_list
        if o.baseline_eligible
        and o.metrics.rsi14 is not None
        and 65.0 < float(o.metrics.rsi14) <= 70.0
    ]
    return arm_kpi(band, eligible="baseline_eligible") | {
        "count": len(band),
        "note": "Baseline-eligible with RSI in (65, 70]",
    }


def _bucket_kpi(
    obs_list: Sequence[ForwardObs],
    *,
    eligible: str,
    bucket_fn,
) -> dict[str, Any]:
    groups: dict[str, list[ForwardObs]] = defaultdict(list)
    for o in obs_list:
        if not getattr(o, eligible):
            continue
        key = bucket_fn(o)
        if key is None:
            continue
        groups[key].append(o)
    out: dict[str, Any] = {}
    for key, rows in sorted(groups.items()):
        nets = [float(r.outcome.get("net_pnl_krw") or 0) for r in rows]
        wins = sum(1 for n in nets if n > 0)
        early = sum(1 for r in rows if r.early_dump)
        out[key] = {
            "count": len(rows),
            "wins": wins,
            "losses": sum(1 for n in nets if n < 0),
            "net": round(sum(nets), 4),
            "avg_net": _avg(nets),
            "early_dump_rate": round(early / len(rows), 4) if rows else None,
        }
    return out


def analyze_exhaustion_patterns(obs_list: Sequence[ForwardObs]) -> dict[str, Any]:
    """상승 끝물 패턴 — 사후 최적화 금지, 고정 bucket."""

    def rsi_bucket(o: ForwardObs) -> str | None:
        r = o.metrics.rsi14
        if r is None:
            return None
        v = float(r)
        if v <= 55:
            return "rsi_le_55"
        if v <= 60:
            return "rsi_55_60"
        if v <= 65:
            return "rsi_60_65"
        if v <= 70:
            return "rsi_65_70"
        return "rsi_gt_70"

    def ma_bucket(o: ForwardObs) -> str | None:
        s = o.metrics.ma_separation_pct
        if s is None:
            return None
        v = float(s)
        if v < 0.05:
            return None
        if v < 0.10:
            return "ma_0_05_0_10"
        if v < 0.20:
            return "ma_0_10_0_20"
        if v < 0.50:
            return "ma_0_20_0_50"
        return "ma_ge_0_50"

    def vol_bucket(o: ForwardObs) -> str | None:
        s = o.metrics.volume_surge
        if s is None:
            return None
        v = float(s)
        if v < 0.8:
            return None
        if v < 1.0:
            return "vol_0_8_1_0"
        if v < 1.5:
            return "vol_1_0_1_5"
        if v < 2.0:
            return "vol_1_5_2_0"
        if v < 3.0:
            return "vol_2_0_3_0"
        return "vol_ge_3"

    # pre-entry / local-high: feature 없으면 NOT_AVAILABLE
    pre_avail = sum(
        1
        for o in obs_list
        if o.features.get("pre_entry_return_5m") not in (None, "NOT_AVAILABLE")
    )
    high_avail = sum(
        1
        for o in obs_list
        if o.features.get("dist_from_15m_high_pct") not in (None, "NOT_AVAILABLE")
    )

    return {
        "PRE_ENTRY_SPIKE": {
            "status": "AVAILABLE" if pre_avail else "NOT_AVAILABLE",
            "available_rows": pre_avail,
            "note": "requires entry_forward_features.pre_entry_return_* stamp",
        },
        "NEAR_LOCAL_HIGH": {
            "status": "AVAILABLE" if high_avail else "NOT_AVAILABLE",
            "available_rows": high_avail,
            "note": "requires entry_forward_features.dist_from_*_high_pct stamp",
        },
        "RSI_EXHAUSTION": {
            "baseline": _bucket_kpi(obs_list, eligible="baseline_eligible", bucket_fn=rsi_bucket),
            "b1": _bucket_kpi(obs_list, eligible="b1_eligible", bucket_fn=rsi_bucket),
        },
        "MA_EXTENSION": {
            "baseline": _bucket_kpi(obs_list, eligible="baseline_eligible", bucket_fn=ma_bucket),
            "b1": _bucket_kpi(obs_list, eligible="b1_eligible", bucket_fn=ma_bucket),
        },
        "VOLUME_EXHAUSTION": {
            "baseline": _bucket_kpi(obs_list, eligible="baseline_eligible", bucket_fn=vol_bucket),
            "b1": _bucket_kpi(obs_list, eligible="b1_eligible", bucket_fn=vol_bucket),
        },
    }


def time_stability(obs_list: Sequence[ForwardObs]) -> dict[str, Any]:
    ordered = sorted(
        obs_list,
        key=lambda o: (
            o.detected_at or datetime.min.replace(tzinfo=timezone.utc),
            o.shadow_id,
        ),
    )
    n = len(ordered)
    if n == 0:
        return {"chunks": {}, "b1_beats_baseline_majority": False}
    a = n // 3
    b = 2 * n // 3
    chunks = {
        "EARLY": ordered[:a] if a else ordered[:1],
        "MIDDLE": ordered[a:b] if b > a else [],
        "LATE": ordered[b:] if b < n else ordered[-1:],
    }
    result: dict[str, Any] = {"chunk_sizes": {k: len(v) for k, v in chunks.items()}}
    beats = 0
    compared = 0
    for name, rows in chunks.items():
        if not rows:
            result[name] = None
            continue
        base = arm_kpi(rows, eligible="baseline_eligible")
        b1 = arm_kpi(rows, eligible="b1_eligible")
        better = float(b1.get("net_pnl") or 0) > float(base.get("net_pnl") or 0)
        compared += 1
        if better:
            beats += 1
        result[name] = {
            "baseline_net": base.get("net_pnl"),
            "baseline_pf": base.get("profit_factor"),
            "b1_net": b1.get("net_pnl"),
            "b1_pf": b1.get("profit_factor"),
            "b1_better_net": better,
        }
    result["b1_beats_baseline_majority"] = compared > 0 and beats >= (compared / 2.0)
    result["b1_beats_count"] = beats
    result["compared_chunks"] = compared
    return result


def symbol_concentration(obs_list: Sequence[ForwardObs], *, eligible: str) -> dict[str, Any]:
    by_sym: dict[str, list[float]] = defaultdict(list)
    for o in obs_list:
        if getattr(o, eligible):
            by_sym[o.symbol].append(float(o.outcome.get("net_pnl_krw") or 0))
    rows = []
    for sym, nets in by_sym.items():
        wins = sum(1 for n in nets if n > 0)
        losses = sum(1 for n in nets if n < 0)
        gross_wins = sum(n for n in nets if n > 0)
        gross_losses = abs(sum(n for n in nets if n < 0))
        pf = (
            round(gross_wins / gross_losses, 4)
            if gross_losses > 0
            else (None if gross_wins == 0 else None)
        )
        rows.append(
            {
                "symbol": sym,
                "sample": len(nets),
                "wins": wins,
                "losses": losses,
                "net": round(sum(nets), 4),
                "profit_factor": pf,
            }
        )
    rows.sort(key=lambda r: r["net"])
    top = list(reversed(rows[-5:])) if rows else []
    bottom = rows[:5]
    pos_nets = [r for r in rows if r["net"] > 0]
    total_pos = sum(r["net"] for r in pos_nets) or 0.0
    top1_share = None
    if pos_nets and total_pos > 0:
        top1_share = round(max(r["net"] for r in pos_nets) / total_pos, 4)
    return {
        "top_symbols": top,
        "bottom_symbols": bottom,
        "top1_positive_net_share": top1_share,
        "concentrated": (
            top1_share is not None and top1_share > SYMBOL_CONCENTRATION_MAX_SHARE
        ),
        "note": "diagnostic only — no symbol blacklist/whitelist",
    }


def fee_efficiency(
    baseline: dict[str, Any], b1: dict[str, Any], attr: dict[str, Any]
) -> dict[str, Any]:
    b_gross = float(baseline.get("gross_pnl") or 0)
    b_fees = float(baseline.get("fees") or 0)
    b_net = float(baseline.get("net_pnl") or 0)
    c_gross = float(b1.get("gross_pnl") or 0)
    c_fees = float(b1.get("fees") or 0)
    c_net = float(b1.get("net_pnl") or 0)
    # quality vs fee-only: filter benefit + avg_mfe improvement
    fee_reduction = b_fees - c_fees
    net_improvement = c_net - b_net
    return {
        "baseline": {
            "gross_edge": round(b_gross, 4),
            "fee_drag": round(b_fees, 4),
            "net_edge": round(b_net, 4),
        },
        "b1": {
            "gross_edge": round(c_gross, 4),
            "fee_drag": round(c_fees, 4),
            "net_edge": round(c_net, 4),
        },
        "fee_reduction_from_fewer_trades": round(fee_reduction, 4),
        "net_improvement": round(net_improvement, 4),
        "net_filter_benefit": attr.get("net_filter_benefit"),
        "quality_improved_beyond_fee": bool(
            float(attr.get("net_filter_benefit") or 0) > fee_reduction * 0.5
            and (b1.get("avg_mfe") or 0) >= (baseline.get("avg_mfe") or 0)
        ),
        "notional_krw": 10000,
    }


def evaluate_promotion_gates(
    *,
    combined_n: int,
    new_n: int,
    baseline: dict[str, Any],
    b1: dict[str, Any],
    early_base: float | None,
    early_b1: float | None,
    stability: dict[str, Any],
    concentration: dict[str, Any],
) -> dict[str, Any]:
    failures: list[str] = []
    gates: dict[str, bool] = {}

    gates["A_combined_ge_1000"] = combined_n >= TARGET_COMBINED_OPPORTUNITIES
    gates["B_new_ge_500"] = new_n >= TARGET_NEW_UNSEEN
    gates["C_b1_net_gt_0"] = float(b1.get("net_pnl") or 0) > 0
    b1_pf = b1.get("profit_factor")
    gates["D_b1_pf_gt_1"] = b1_pf is not None and float(b1_pf) > 1.0
    gates["E_b1_net_gt_baseline"] = float(b1.get("net_pnl") or 0) > float(
        baseline.get("net_pnl") or 0
    )
    base_pf = baseline.get("profit_factor")
    if b1_pf is None or base_pf is None:
        gates["F_b1_pf_gt_baseline"] = False
    else:
        gates["F_b1_pf_gt_baseline"] = float(b1_pf) > float(base_pf)

    b_max = baseline.get("max_loss")
    c_max = b1.get("max_loss")
    # max_loss는 음수; 악화 = 더 음수
    if b_max is None or c_max is None:
        gates["G_max_loss_not_worsened"] = False
    else:
        gates["G_max_loss_not_worsened"] = float(c_max) >= float(b_max)

    if early_base is None or early_b1 is None:
        gates["H_early_dump_reduced"] = False
    else:
        gates["H_early_dump_reduced"] = float(early_b1) <= float(early_base)

    gates["I_not_symbol_concentrated"] = not bool(concentration.get("concentrated"))
    gates["J_time_stability_majority"] = bool(
        stability.get("b1_beats_baseline_majority")
    )

    for k, ok in gates.items():
        if not ok:
            failures.append(k)

    sample_ready = gates["A_combined_ge_1000"] and gates["B_new_ge_500"]
    all_pass = all(gates.values())

    if not sample_ready:
        verdict = VERDICT_COLLECTING
        next_action = NEXT_COLLECT
        promo = "NO"
        status = "NOT READY"
    elif all_pass:
        verdict = VERDICT_REVIEW_READY
        next_action = NEXT_REVIEW_PASS
        promo = "NO"  # 자동 적용 금지 — REVIEW ONLY
        status = "REVIEW READY"
    else:
        verdict = VERDICT_GATES_FAILED
        next_action = NEXT_REVIEW_FAIL
        promo = "NO"
        status = "NOT READY"

    return {
        "gates": gates,
        "PROMOTION_GATE_FAILURES": failures,
        "all_gates_passed": all_pass,
        "FINAL_VERDICT": verdict,
        "REAL_PROMOTION_RECOMMENDED": promo,
        "PROMOTION_STATUS": status,
        "NEXT_ACTION": next_action,
        "AUTO_PROMOTE": False,
        "note": "All gates pass → REVIEW READY only; never auto-apply to REAL",
    }


def daily_research_summary(obs_list: Sequence[ForwardObs], *, day: date | None = None) -> dict[str, Any]:
    """KST 일일 연구 summary — Telegram 1회용 payload."""

    day = day or datetime.now(KST).date()
    today_rows = []
    for o in obs_list:
        if o.detected_at is None:
            continue
        if o.detected_at.astimezone(KST).date() == day:
            today_rows.append(o)
    base = arm_kpi(obs_list, eligible="baseline_eligible")
    b1 = arm_kpi(obs_list, eligible="b1_eligible")
    attr = filter_attribution(obs_list)
    legacy_n = sum(1 for o in obs_list if o.cohort == COHORT_LEGACY)
    new_n = sum(1 for o in obs_list if o.cohort == COHORT_NEW)
    return {
        "day_kst": day.isoformat(),
        "today_new_opportunities": len(today_rows),
        "legacy_sample_count": legacy_n,
        "new_sample_count": new_n,
        "combined_sample_count": len(obs_list),
        "progress": {
            "combined": f"{len(obs_list)} / {TARGET_COMBINED_OPPORTUNITIES}",
            "new": f"{new_n} / {TARGET_NEW_UNSEEN}",
        },
        "baseline": {
            "entries": base.get("entries"),
            "wins": base.get("wins"),
            "losses": base.get("losses"),
            "net": base.get("net_pnl"),
            "pf": base.get("profit_factor"),
        },
        "b1": {
            "entries": b1.get("entries"),
            "wins": b1.get("wins"),
            "losses": b1.get("losses"),
            "net": b1.get("net_pnl"),
            "pf": b1.get("profit_factor"),
        },
        "filter": attr,
        "early_dump": {
            "baseline_rate": base.get("early_dump_rate"),
            "b1_rate": b1.get("early_dump_rate"),
        },
        "REAL_policy_changed": "NO",
    }


def run_b1_forward_validation(rows: Sequence[Any]) -> dict[str, Any]:
    """COMPLETED shadow rows → B1 forward validation report."""

    obs = assign_cohorts(rows)
    legacy_n = sum(1 for o in obs if o.cohort == COHORT_LEGACY)
    new_n = sum(1 for o in obs if o.cohort == COHORT_NEW)
    combined_n = len(obs)

    baseline = arm_kpi(obs, eligible="baseline_eligible")
    b1 = arm_kpi(obs, eligible="b1_eligible")
    attr = filter_attribution(obs)
    rsi_band = rsi_65_70_band(obs)
    exhaustion = analyze_exhaustion_patterns(obs)
    stability = time_stability(obs)
    concentration = symbol_concentration(obs, eligible="b1_eligible")
    fees = fee_efficiency(baseline, b1, attr)

    new_obs = [o for o in obs if o.cohort == COHORT_NEW]
    new_baseline = arm_kpi(new_obs, eligible="baseline_eligible") if new_obs else None
    new_b1 = arm_kpi(new_obs, eligible="b1_eligible") if new_obs else None

    promo = evaluate_promotion_gates(
        combined_n=combined_n,
        new_n=new_n,
        baseline=baseline,
        b1=b1,
        early_base=baseline.get("early_dump_rate"),
        early_b1=b1.get("early_dump_rate"),
        stability=stability,
        concentration=concentration,
    )

    progress = {
        "combined": f"{combined_n} / {TARGET_COMBINED_OPPORTUNITIES}",
        "new": f"{new_n} / {TARGET_NEW_UNSEEN}",
        "combined_ratio": round(combined_n / TARGET_COMBINED_OPPORTUNITIES, 4),
        "new_ratio": round(new_n / TARGET_NEW_UNSEEN, 4),
        "SAMPLE_COLLECTION_IN_PROGRESS": combined_n < TARGET_COMBINED_OPPORTUNITIES
        or new_n < TARGET_NEW_UNSEEN,
    }

    return {
        "schema": "entry_b1_forward_validation_v1",
        "preferred_candidate": LABEL_B1,
        "policies": {
            "baseline": {
                "rsi_max": ENTRY_BASELINE_SPEC.rsi_max,
                "min_volume_surge": ENTRY_BASELINE_SPEC.min_volume_surge,
                "min_ma_separation_pct": ENTRY_BASELINE_SPEC.min_ma_separation_pct,
                "ai": "ALLOW",
            },
            "b1": {
                "rsi_max": ENTRY_CANDIDATE_B1_SPEC.rsi_max,
                "min_volume_surge": ENTRY_CANDIDATE_B1_SPEC.min_volume_surge,
                "min_ma_separation_pct": ENTRY_CANDIDATE_B1_SPEC.min_ma_separation_pct,
                "ai": "ALLOW",
            },
            "exit": {
                "tp_pct": EXIT_BASELINE_SPEC.tp_pct,
                "trail_distance_pct": EXIT_BASELINE_SPEC.trail_distance_pct,
                "sl_pct": EXIT_BASELINE_SPEC.sl_pct,
                "note": "identical for both arms; Candidate A unused",
            },
            "candidate_b_vol10_excluded": True,
        },
        "legacy_sample_count": legacy_n,
        "new_sample_count": new_n,
        "combined_sample_count": combined_n,
        "progress": progress,
        "baseline": baseline,
        "b1": b1,
        "new_unseen_only": {
            "baseline": new_baseline,
            "b1": new_b1,
        },
        "filter_attribution": attr,
        "rsi_65_70_band": rsi_band,
        "early_dump": {
            "definition": EARLY_DUMP_DEFINITION,
            "baseline_early_dump_count": baseline.get("early_dump_count"),
            "baseline_early_dump_rate": baseline.get("early_dump_rate"),
            "b1_early_dump_count": b1.get("early_dump_count"),
            "b1_early_dump_rate": b1.get("early_dump_rate"),
        },
        "exhaustion_patterns": exhaustion,
        "time_stability": stability,
        "symbol_concentration": concentration,
        "fee_efficiency": fees,
        "daily_summary": daily_research_summary(obs),
        "persistence_sot": (
            "trading.upbit_opportunity_shadow.evaluation_detail "
            "(exit_ab / entry_ab / entry_forward_features) — no duplicate table"
        ),
        "mutations": {
            "REAL_POLICY_MUTATION": 0,
            "REAL_ORDER_FORCE_MUTATION": 0,
            "EXIT_POLICY_MUTATION": 0,
            "RISK_MUTATION": 0,
            "SLOT_POLICY_MUTATION": 0,
            "UBA1381_MUTATION": 0,
        },
        "AUTO_PROMOTE": False,
        **promo,
        "dashboard": {
            "card": "Entry Forward Validation",
            "candidate": "RSI65 / VOL0.8",
            "progress": progress,
            "promotion": promo.get("PROMOTION_STATUS"),
        },
    }


def summarize_b1_forward_from_shadows(rows: Sequence[Any]) -> dict[str, Any]:
    """stats.py / API용 thin wrapper — research 실패 시 호출측에서 fail-open."""

    try:
        return run_b1_forward_validation(rows)
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "entry_b1_forward_validation_v1",
            "error": str(exc)[:300],
            "FINAL_VERDICT": VERDICT_COLLECTING,
            "REAL_PROMOTION_RECOMMENDED": "NO",
            "AUTO_PROMOTE": False,
            "research_failed_open": True,
            "note": "research failure must not block REAL",
        }
