"""Shadow/Paper Entry Policy A/B — Baseline vs Candidate B (REAL 정책 미변경).

동일 opportunity 시점에 두 entry gate만 비교한다.
Exit는 항상 REAL baseline (TP10 / trail3) — Candidate A exit 금지.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from stock_platform.operation.upbit_full_market.constants import (
    ALLOW_RECOMMENDATIONS,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_policy_ab import (
    BASELINE_SPEC as EXIT_BASELINE_SPEC,
    _arm_kpis,
)

# ── Entry 정책 (grid 금지 — Baseline vs Candidate B만) ─────────────────────

POLICY_BASELINE = "ENTRY_BASELINE"
POLICY_CANDIDATE_B = "ENTRY_CANDIDATE_B"

FORWARD_SAMPLE_MIN = 100
# trade count가 Baseline 대비 이 비율 미만이면 과도한 축소
MIN_TRADE_FREQUENCY_RATIO = 0.50

VERDICT_VALIDATED = "ENTRY_CANDIDATE_B_FORWARD_VALIDATED"
VERDICT_REJECTED = "ENTRY_CANDIDATE_B_REJECTED"
VERDICT_RUNNING = "ENTRY_CANDIDATE_B_VALIDATION_RUNNING"

NEXT_REVIEW = "REVIEW_ENTRY_CANDIDATE_B_FOR_REAL_PROMOTION"
NEXT_KEEP = "KEEP_CURRENT_REAL_POLICY_AND_COLLECT_MORE_DATA"
NEXT_COLLECT = "COLLECT_MORE_ENTRY_AB_FORWARD_SAMPLE"

# Candidate A exit 검증은 REJECTED 유지 — 이 모듈에서 사용 금지
CANDIDATE_A_EXIT_REJECTED = True


@dataclass(frozen=True, slots=True)
class EntryPolicySpec:
    """Entry-only 스펙. Exit/MA anti-churn/Risk 불변."""

    label: str
    rsi_max: float
    min_volume_surge: float
    min_ma_separation_pct: float = 0.05
    require_ai_allow: bool = True


ENTRY_BASELINE_SPEC = EntryPolicySpec(
    label=POLICY_BASELINE,
    rsi_max=70.0,
    min_volume_surge=0.8,
    min_ma_separation_pct=0.05,
    require_ai_allow=True,
)

ENTRY_CANDIDATE_B_SPEC = EntryPolicySpec(
    label=POLICY_CANDIDATE_B,
    rsi_max=65.0,
    min_volume_surge=1.0,
    min_ma_separation_pct=0.05,
    require_ai_allow=True,
)

# 진단용 attribution (승격 후보 아님)
ENTRY_RSI65_ONLY_SPEC = EntryPolicySpec(
    label="ATTR_RSI65_ONLY",
    rsi_max=65.0,
    min_volume_surge=0.8,
    min_ma_separation_pct=0.05,
    require_ai_allow=True,
)

ENTRY_VOL10_ONLY_SPEC = EntryPolicySpec(
    label="ATTR_VOL10_ONLY",
    rsi_max=70.0,
    min_volume_surge=1.0,
    min_ma_separation_pct=0.05,
    require_ai_allow=True,
)


@dataclass(frozen=True, slots=True)
class OpportunityMetrics:
    """동일 시점 opportunity 지표 (lookahead 금지 — 저장값만)."""

    symbol: str
    scanner_score: float | None
    ai_recommendation: str | None
    ma_separation_pct: float | None
    short_ma: float | None
    long_ma: float | None
    rsi14: float | None
    volume_surge: float | None


def ma_separation_pct(
    short_ma: float | None, long_ma: float | None
) -> float | None:
    if short_ma is None or long_ma is None:
        return None
    if float(long_ma) == 0:
        return None
    return (float(short_ma) - float(long_ma)) / float(long_ma) * 100.0


def evaluate_entry_eligibility(
    metrics: OpportunityMetrics,
    spec: EntryPolicySpec,
) -> tuple[bool, str | None]:
    """Shadow 시점 entry gate. feed/candidate age는 스냅샷 고정이라 생략."""

    if metrics.short_ma is None or metrics.long_ma is None:
        return False, "MISSING_MA"
    if float(metrics.short_ma) <= float(metrics.long_ma):
        return False, "SHORT_MA_NOT_ABOVE_LONG_MA"

    sep = metrics.ma_separation_pct
    if sep is None:
        sep = ma_separation_pct(metrics.short_ma, metrics.long_ma)
    if sep is None or float(sep) < float(spec.min_ma_separation_pct):
        return False, "MA_SEPARATION_TOO_SMALL"

    if spec.require_ai_allow:
        rec = str(metrics.ai_recommendation or "").upper()
        if rec not in ALLOW_RECOMMENDATIONS:
            return False, "AI_SELECTION_NOT_ALLOW"

    if metrics.rsi14 is None:
        return False, "MISSING_RSI"
    if float(metrics.rsi14) > float(spec.rsi_max):
        return False, "RSI_TOO_HIGH"

    if metrics.volume_surge is None:
        return False, "MISSING_VOLUME_SURGE"
    if float(metrics.volume_surge) < float(spec.min_volume_surge):
        return False, "VOLUME_SURGE_TOO_LOW"

    return True, None


def metrics_from_shadow_row(row: Any) -> OpportunityMetrics:
    """COMPLETED shadow 행 → opportunity metrics."""

    short = getattr(row, "ma5", None)
    long = getattr(row, "ma20", None)
    snap = getattr(row, "entry_snapshot", None) or {}
    cand = snap.get("candidate") if isinstance(snap, dict) else None
    cand = cand if isinstance(cand, dict) else {}
    sep = cand.get("ma_spread_pct")
    if sep is None:
        sep = ma_separation_pct(
            float(short) if short is not None else None,
            float(long) if long is not None else None,
        )
    return OpportunityMetrics(
        symbol=str(getattr(row, "symbol", "") or ""),
        scanner_score=(
            float(row.scanner_score)
            if getattr(row, "scanner_score", None) is not None
            else None
        ),
        ai_recommendation=str(getattr(row, "recommendation", "") or "") or None,
        ma_separation_pct=float(sep) if sep is not None else None,
        short_ma=float(short) if short is not None else None,
        long_ma=float(long) if long is not None else None,
        rsi14=(
            float(row.rsi14) if getattr(row, "rsi14", None) is not None else None
        ),
        volume_surge=(
            float(row.volume_surge)
            if getattr(row, "volume_surge", None) is not None
            else None
        ),
    )


def baseline_exit_outcome(row: Any) -> dict[str, Any] | None:
    """Exit Candidate A 금지 — evaluation_detail.exit_ab.baseline만 사용."""

    detail = getattr(row, "evaluation_detail", None) or {}
    if not isinstance(detail, dict):
        return None
    ab = detail.get("exit_ab")
    if not isinstance(ab, dict):
        return None
    baseline = ab.get("baseline")
    if not isinstance(baseline, dict):
        return None
    # 안전: candidate_a를 성과에 쓰지 않음
    return dict(baseline)


def is_early_dump_proxy(row: Any) -> bool:
    """진입 직후 1~5분 급락 proxy — 특정 심볼 하드코딩 금지.

    return_5m_pct < -0.3 또는 (mae_pct <= -0.5 and holding 짧은 경우).
    """

    r5 = getattr(row, "return_5m_pct", None)
    if r5 is not None and float(r5) <= -0.3:
        return True
    detail = getattr(row, "evaluation_detail", None) or {}
    windows = detail.get("windows") if isinstance(detail, dict) else None
    if isinstance(windows, dict):
        w5 = windows.get("5") or {}
        ret = w5.get("return_pct")
        if ret is not None and float(ret) <= -0.3:
            return True
    outcome = baseline_exit_outcome(row)
    if outcome is None:
        return False
    hold = outcome.get("holding_seconds")
    mae = getattr(row, "mae_pct", None)
    if (
        hold is not None
        and float(hold) <= 180
        and mae is not None
        and float(mae) <= -0.5
    ):
        return True
    return False


def compare_entry_on_opportunity(row: Any) -> dict[str, Any] | None:
    """동일 opportunity에 Baseline / Candidate B eligibility + 동일 exit outcome."""

    metrics = metrics_from_shadow_row(row)
    outcome = baseline_exit_outcome(row)
    if outcome is None:
        return None

    b_ok, b_reason = evaluate_entry_eligibility(metrics, ENTRY_BASELINE_SPEC)
    c_ok, c_reason = evaluate_entry_eligibility(metrics, ENTRY_CANDIDATE_B_SPEC)
    rsi_ok, rsi_reason = evaluate_entry_eligibility(
        metrics, ENTRY_RSI65_ONLY_SPEC
    )
    vol_ok, vol_reason = evaluate_entry_eligibility(
        metrics, ENTRY_VOL10_ONLY_SPEC
    )

    return {
        "schema": "entry_policy_ab_v1",
        "same_opportunity": True,
        "symbol": metrics.symbol,
        "shadow_id": int(getattr(row, "shadow_id", 0) or 0),
        "scanner_score": metrics.scanner_score,
        "ai": metrics.ai_recommendation,
        "ma_separation_pct": metrics.ma_separation_pct,
        "rsi14": metrics.rsi14,
        "volume_surge": metrics.volume_surge,
        "baseline_eligible": b_ok,
        "baseline_block_reason": b_reason,
        "candidate_b_eligible": c_ok,
        "candidate_b_block_reason": c_reason,
        "attr_rsi65_only_eligible": rsi_ok,
        "attr_rsi65_only_block_reason": rsi_reason,
        "attr_vol10_only_eligible": vol_ok,
        "attr_vol10_only_block_reason": vol_reason,
        "exit_policy": {
            "label": EXIT_BASELINE_SPEC.label,
            "tp_pct": EXIT_BASELINE_SPEC.tp_pct,
            "trail_distance_pct": EXIT_BASELINE_SPEC.trail_distance_pct,
            "trail_activation_pct": EXIT_BASELINE_SPEC.trail_activation_pct,
            "note": "REAL baseline exit only — Candidate A TP1/trail unused",
        },
        "outcome": outcome,
        "early_dump_proxy": is_early_dump_proxy(row),
        "mfe_pct": getattr(row, "mfe_pct", None),
        "mae_pct": getattr(row, "mae_pct", None),
        "real_order": False,
        "real_policy_mutation": False,
        "candidate_a_exit_used": False,
    }


def _kpi_from_outcomes(outcomes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return _arm_kpis(list(outcomes))


def _avg(vals: Sequence[float]) -> float | None:
    if not vals:
        return None
    return round(sum(vals) / len(vals), 6)


def analyze_filter_delta(
    observations: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Baseline 통과 · Candidate B 차단 거래 → avoided loser / missed winner."""

    missed_winners: list[dict[str, Any]] = []
    avoided_losers: list[dict[str, Any]] = []
    for obs in observations:
        if not obs.get("baseline_eligible"):
            continue
        if obs.get("candidate_b_eligible"):
            continue
        out = obs.get("outcome") or {}
        net = float(out.get("net_pnl_krw") or 0.0)
        row = {
            "symbol": obs.get("symbol"),
            "shadow_id": obs.get("shadow_id"),
            "rsi14": obs.get("rsi14"),
            "volume_surge": obs.get("volume_surge"),
            "net_pnl_krw": net,
            "block_reason": obs.get("candidate_b_block_reason"),
            "early_dump_proxy": obs.get("early_dump_proxy"),
        }
        if net > 0:
            missed_winners.append(row)
        elif net < 0:
            avoided_losers.append(row)

    missed_net = sum(float(x["net_pnl_krw"]) for x in missed_winners)
    avoided_net = sum(float(x["net_pnl_krw"]) for x in avoided_losers)
    # avoided_loss_value = 회피한 손실의 절대값 (양수 = benefit)
    avoided_loss_value = abs(avoided_net)
    missed_profit_value = missed_net  # 놓친 이익 (양수 = cost)

    return {
        "missed_winner_count": len(missed_winners),
        "missed_winner_net": round(missed_net, 4),
        "missed_profit_value": round(missed_profit_value, 4),
        "avoided_loser_count": len(avoided_losers),
        "avoided_loser_net": round(avoided_net, 4),
        "avoided_loss_value": round(avoided_loss_value, 4),
        "net_filter_benefit": round(avoided_loss_value - missed_profit_value, 4),
        "filter_benefit_positive": avoided_loss_value > missed_profit_value,
        "missed_winners_sample": missed_winners[:10],
        "avoided_losers_sample": avoided_losers[:10],
    }


def analyze_early_dump(
    observations: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """강한 후보인데 직후 하락 — Candidate B가 줄이는지."""

    base_dumps = [
        o
        for o in observations
        if o.get("baseline_eligible") and o.get("early_dump_proxy")
    ]
    cand_dumps = [
        o
        for o in observations
        if o.get("candidate_b_eligible") and o.get("early_dump_proxy")
    ]
    filtered_dumps = [
        o
        for o in base_dumps
        if not o.get("candidate_b_eligible")
    ]
    return {
        "baseline_early_dump_count": len(base_dumps),
        "candidate_b_early_dump_count": len(cand_dumps),
        "early_dumps_filtered_by_b": len(filtered_dumps),
        "early_dump_reduction": len(base_dumps) - len(cand_dumps),
        "note": "proxy: return_5m<=-0.3 or short-hold deep MAE; no symbol hardcode",
    }


def _attribution_arm(
    observations: Sequence[dict[str, Any]],
    eligible_key: str,
) -> dict[str, Any]:
    outs = [
        o["outcome"]
        for o in observations
        if o.get(eligible_key) and isinstance(o.get("outcome"), dict)
    ]
    kpi = _kpi_from_outcomes(outs)
    kpi["entries"] = len(outs)
    return kpi


def decide_entry_candidate_b(
    *,
    opportunity_count: int,
    baseline_kpi: dict[str, Any],
    candidate_kpi: dict[str, Any],
    filter_delta: dict[str, Any],
) -> dict[str, Any]:
    """승격 후보 판정 — 승률만 좋아지면 금지."""

    if opportunity_count < FORWARD_SAMPLE_MIN:
        return {
            "candidate_superiority": "INSUFFICIENT",
            "final_verdict": VERDICT_RUNNING,
            "next_action": NEXT_COLLECT,
            "reasons": ["INSUFFICIENT_FORWARD_SAMPLE"],
        }

    b_entries = int(baseline_kpi.get("sample_count") or 0)
    c_entries = int(candidate_kpi.get("sample_count") or 0)
    if b_entries < FORWARD_SAMPLE_MIN and opportunity_count < FORWARD_SAMPLE_MIN:
        return {
            "candidate_superiority": "INSUFFICIENT",
            "final_verdict": VERDICT_RUNNING,
            "next_action": NEXT_COLLECT,
            "reasons": ["INSUFFICIENT_ELIGIBLE_ENTRIES"],
        }

    reasons: list[str] = []
    net_ok = float(candidate_kpi.get("net_pnl") or 0) > float(
        baseline_kpi.get("net_pnl") or 0
    )
    b_pf = baseline_kpi.get("profit_factor")
    c_pf = candidate_kpi.get("profit_factor")
    if b_pf is None and c_pf is None:
        pf_ok = False
        reasons.append("PROFIT_FACTOR_UNDEFINED")
    elif b_pf is None:
        pf_ok = c_pf is not None
    elif c_pf is None:
        pf_ok = False
    else:
        pf_ok = float(c_pf) > float(b_pf)

    b_max = float(baseline_kpi.get("max_trade_loss") or 0)
    c_max = float(candidate_kpi.get("max_trade_loss") or 0)
    if b_max < 0:
        max_loss_ok = c_max >= (b_max * 1.25)
    else:
        max_loss_ok = c_max >= b_max

    filter_ok = bool(filter_delta.get("filter_benefit_positive"))
    freq_ratio = (c_entries / b_entries) if b_entries > 0 else 0.0
    freq_ok = freq_ratio >= MIN_TRADE_FREQUENCY_RATIO
    safety_ok = True  # entry-only; exit/SL unchanged by construction

    if not net_ok:
        reasons.append("NET_RETURN_NOT_BETTER")
    if not pf_ok:
        reasons.append("PROFIT_FACTOR_NOT_IMPROVED")
    if not max_loss_ok:
        reasons.append("MAX_LOSS_WORSENED")
    if not filter_ok:
        reasons.append("MISSED_WINNER_COST_GE_AVOIDED_LOSER_BENEFIT")
    if not freq_ok:
        reasons.append("TRADE_FREQUENCY_OVER_REDUCED")
    if not safety_ok:
        reasons.append("SAFETY_REGRESSION")

    superior = (
        net_ok and pf_ok and max_loss_ok and filter_ok and freq_ok and safety_ok
    )
    if superior:
        return {
            "candidate_superiority": "YES",
            "final_verdict": VERDICT_VALIDATED,
            "next_action": NEXT_REVIEW,
            "reasons": ["ALL_PROMOTION_GATES_PASSED"],
            "gates": {
                "net_ok": net_ok,
                "pf_ok": pf_ok,
                "max_loss_ok": max_loss_ok,
                "filter_ok": filter_ok,
                "freq_ok": freq_ok,
                "safety_ok": safety_ok,
                "trade_frequency_ratio": round(freq_ratio, 4),
            },
        }
    return {
        "candidate_superiority": "NO",
        "final_verdict": VERDICT_REJECTED,
        "next_action": NEXT_KEEP,
        "reasons": reasons or ["CANDIDATE_NOT_SUPERIOR"],
        "gates": {
            "net_ok": net_ok,
            "pf_ok": pf_ok,
            "max_loss_ok": max_loss_ok,
            "filter_ok": filter_ok,
            "freq_ok": freq_ok,
            "safety_ok": safety_ok,
            "trade_frequency_ratio": round(freq_ratio, 4),
        },
    }


def aggregate_entry_ab(
    observations: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Forward Shadow Entry A/B 집계."""

    n_opp = len(observations)
    base_outs = [
        o["outcome"]
        for o in observations
        if o.get("baseline_eligible") and isinstance(o.get("outcome"), dict)
    ]
    cand_outs = [
        o["outcome"]
        for o in observations
        if o.get("candidate_b_eligible") and isinstance(o.get("outcome"), dict)
    ]
    base_kpi = _kpi_from_outcomes(base_outs)
    cand_kpi = _kpi_from_outcomes(cand_outs)
    filter_delta = analyze_filter_delta(observations)
    early = analyze_early_dump(observations)

    base_mfe = _avg(
        [
            float(o["mfe_pct"])
            for o in observations
            if o.get("baseline_eligible") and o.get("mfe_pct") is not None
        ]
    )
    cand_mfe = _avg(
        [
            float(o["mfe_pct"])
            for o in observations
            if o.get("candidate_b_eligible") and o.get("mfe_pct") is not None
        ]
    )
    base_mae = _avg(
        [
            float(o["mae_pct"])
            for o in observations
            if o.get("baseline_eligible") and o.get("mae_pct") is not None
        ]
    )
    cand_mae = _avg(
        [
            float(o["mae_pct"])
            for o in observations
            if o.get("candidate_b_eligible") and o.get("mae_pct") is not None
        ]
    )

    rsi_attr = _attribution_arm(observations, "attr_rsi65_only_eligible")
    vol_attr = _attribution_arm(observations, "attr_vol10_only_eligible")
    combined_attr = dict(cand_kpi)
    combined_attr["entries"] = int(cand_kpi.get("sample_count") or 0)

    b_n = int(base_kpi.get("sample_count") or 0)
    c_n = int(cand_kpi.get("sample_count") or 0)
    decision = decide_entry_candidate_b(
        opportunity_count=n_opp,
        baseline_kpi=base_kpi,
        candidate_kpi=cand_kpi,
        filter_delta=filter_delta,
    )

    return {
        "cohort": "FORWARD_SHADOW",
        "opportunity_count": n_opp,
        "sample_count": n_opp,
        "baseline_entries": b_n,
        "candidate_entries": c_n,
        "candidate_filtered_count": max(0, b_n - c_n),
        "trade_frequency_reduction": (
            round(1.0 - (c_n / b_n), 4) if b_n > 0 else None
        ),
        "baseline": {
            **base_kpi,
            "avg_mfe_pct": base_mfe,
            "avg_mae_pct": base_mae,
        },
        "candidate_b": {
            **cand_kpi,
            "avg_mfe_pct": cand_mfe,
            "avg_mae_pct": cand_mae,
        },
        "filter_delta": filter_delta,
        "early_dump_analysis": early,
        "attribution": {
            "rsi65_only": rsi_attr,
            "volume_1_0_only": vol_attr,
            "rsi65_and_volume_1_0": combined_attr,
            "note": "diagnostic only — not promotion candidates",
        },
        "exit_identical": True,
        "exit_policy": "BASELINE_TP10_TRAIL3",
        "candidate_a_exit_rejected": CANDIDATE_A_EXIT_REJECTED,
        "real_order": False,
        "real_policy_mutation": False,
        **decision,
    }


def summarize_entry_ab_from_shadows(rows: Sequence[Any]) -> dict[str, Any]:
    """COMPLETED shadow → Entry A/B 요약."""

    observations: list[dict[str, Any]] = []
    for row in rows:
        obs = compare_entry_on_opportunity(row)
        if obs is not None:
            observations.append(obs)
    return aggregate_entry_ab(observations)
