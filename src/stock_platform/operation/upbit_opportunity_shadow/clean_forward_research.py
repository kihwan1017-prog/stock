"""Clean Forward Research Epoch — fb35aa2 이후 canonical price 기준.

LEGACY 459건 보존·승격 제외. Promotion은 CLEAN sample만 사용.
REAL 정책/주문과 무관.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
    COHORT_LEGACY,
    COHORT_NEW,
    ForwardObs,
    _as_utc,
    build_forward_obs,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_price_resolver import (
    QUALITY_CANONICAL,
    QUALITY_CANDIDATE_MATCH,
)

# fb35aa2 fix(research): canonical shadow entry price — commit UTC
CLEAN_FORWARD_EPOCH_START = datetime(2026, 8, 23, 21, 50, 51, tzinfo=timezone.utc)
CLEAN_EPOCH_SOURCE = "git_commit_fb35aa2_deployed_at_utc"

LEGACY_FORWARD_COUNT = 459
LEGACY_AFFECTED_COUNT = 79
LEGACY_AFFECTED_PCT = 17.2
LEGACY_SAMPLE_QUALITY = "LEGACY_PARTIALLY_COMPROMISED"
HISTORICAL_COMPROMISED_REFERENCE = "HISTORICAL_COMPROMISED_REFERENCE"

TARGET_CLEAN_MIN = 500
TARGET_CLEAN_RECOMMENDED = 1000

COHORT_CLEAN_FORWARD = "CLEAN_FORWARD"
COHORT_STAMPED_BACKFILL = "STAMPED_BACKFILL_ONLY"
COHORT_EXCLUDED = "EXCLUDED_FROM_PROMOTION"

VALID_ENTRY_PRICE_QUALITIES = frozenset(
    {QUALITY_CANONICAL, QUALITY_CANDIDATE_MATCH}
)

WINDOW_MINUTES = (5, 15, 30, 60)


def _detail(row: Any) -> dict[str, Any]:
    d = getattr(row, "evaluation_detail", None)
    return d if isinstance(d, dict) else {}


def _snapshot(row: Any) -> dict[str, Any]:
    s = getattr(row, "entry_snapshot", None)
    return s if isinstance(s, dict) else {}


def _row_created_at(row: Any) -> datetime | None:
    for attr in ("created_at", "detected_at"):
        dt = _as_utc(getattr(row, attr, None))
        if dt is not None:
            return dt
    return None


def is_research_stamp_backfill(row: Any) -> bool:
    detail = _detail(row)
    bf = detail.get("research_stamp_backfill")
    return isinstance(bf, dict) and bool(bf.get("stamped_at"))


def has_canonical_entry_provenance(row: Any) -> bool:
    prov = _snapshot(row).get("entry_price_provenance")
    if not isinstance(prov, dict):
        return False
    quality = str(prov.get("quality") or "")
    source = str(prov.get("source") or "")
    return quality in VALID_ENTRY_PRICE_QUALITIES or (
        "market.candle_minute" in source and prov.get("ok") is True
    )


def is_after_clean_epoch(row: Any) -> bool:
    detected = _as_utc(getattr(row, "detected_at", None))
    created = _as_utc(getattr(row, "created_at", None))
    if detected is not None and detected >= CLEAN_FORWARD_EPOCH_START:
        if created is not None:
            return created >= CLEAN_FORWARD_EPOCH_START
        return True
    return False


def has_research_stamps(row: Any) -> bool:
    detail = _detail(row)
    exit_ab = detail.get("exit_ab")
    if not isinstance(exit_ab, dict) or not isinstance(exit_ab.get("baseline"), dict):
        return False
    if not isinstance(detail.get("entry_ab"), dict):
        return False
    fwd = detail.get("entry_forward_features")
    return isinstance(fwd, dict) and fwd.get("ok") is True


def is_time_alignment_valid(row: Any) -> bool:
    windows = _detail(row).get("windows")
    if not isinstance(windows, dict):
        return False
    for minutes in WINDOW_MINUTES:
        w = windows.get(str(minutes))
        if not isinstance(w, dict):
            return False
        if str(w.get("status") or "") != "OK":
            return False
        if w.get("price") is None or w.get("return_pct") is None:
            return False
    return True


def classify_forward_row(row: Any) -> dict[str, Any]:
    """단일 row 분류 — DB UPDATE 없음."""

    detected = _as_utc(getattr(row, "detected_at", None))
    sid = int(getattr(row, "shadow_id", 0) or 0)
    reasons: list[str] = []
    exclusions: list[str] = []

    if is_research_stamp_backfill(row):
        reasons.append("RESEARCH_STAMP_BACKFILL")
        return {
            "shadow_id": sid,
            "cohort": COHORT_STAMPED_BACKFILL,
            "promotion_eligible": False,
            "clean": False,
            "reasons": reasons,
            "exclusions": ["BACKFILL_NOT_CLEAN_OBSERVATION"],
        }

    if not is_after_clean_epoch(row):
        reasons.append("BEFORE_CLEAN_EPOCH")
        exclusions.append("BEFORE_CLEAN_EPOCH")
        if detected is not None and detected < CLEAN_FORWARD_EPOCH_START:
            return {
                "shadow_id": sid,
                "cohort": COHORT_LEGACY,
                "promotion_eligible": False,
                "clean": False,
                "reasons": reasons,
                "exclusions": exclusions,
            }

    if not has_canonical_entry_provenance(row):
        exclusions.append("INVALID_PRICE_SOURCE")
    if not has_research_stamps(row):
        exclusions.append("MISSING_RESEARCH_STAMPS")
    if not is_time_alignment_valid(row):
        exclusions.append("INVALID_TIME_ALIGNMENT")

    clean = (
        not exclusions
        and is_after_clean_epoch(row)
        and has_canonical_entry_provenance(row)
        and has_research_stamps(row)
        and is_time_alignment_valid(row)
        and not is_research_stamp_backfill(row)
    )

    if clean:
        return {
            "shadow_id": sid,
            "cohort": COHORT_CLEAN_FORWARD,
            "promotion_eligible": True,
            "clean": True,
            "reasons": ["CANONICAL_CLEAN_EPOCH_SAMPLE"],
            "exclusions": [],
        }

    return {
        "shadow_id": sid,
        "cohort": COHORT_EXCLUDED,
        "promotion_eligible": False,
        "clean": False,
        "reasons": reasons or ["QUALITY_GATE_FAILED"],
        "exclusions": exclusions,
    }


def partition_forward_rows(rows: Sequence[Any]) -> dict[str, Any]:
    """전체 row → legacy / stamped / clean / excluded 집계."""

    legacy_rows: list[Any] = []
    stamped_rows: list[Any] = []
    clean_rows: list[Any] = []
    excluded_rows: list[Any] = []
    excluded_invalid_price = 0
    excluded_alignment = 0

    for row in rows:
        cls = classify_forward_row(row)
        if cls["cohort"] == COHORT_LEGACY:
            legacy_rows.append(row)
        elif cls["cohort"] == COHORT_STAMPED_BACKFILL:
            stamped_rows.append(row)
        elif cls["cohort"] == COHORT_CLEAN_FORWARD:
            clean_rows.append(row)
        else:
            excluded_rows.append(row)
        for ex in cls.get("exclusions") or []:
            if ex == "INVALID_PRICE_SOURCE":
                excluded_invalid_price += 1
            if ex == "INVALID_TIME_ALIGNMENT":
                excluded_alignment += 1

    # assign_cohorts 기준 legacy count (기존 459 SoT)
    legacy_obs = [
        o
        for o in (
            build_forward_obs(r, cohort=COHORT_LEGACY)
            for r in legacy_rows
            if build_forward_obs(r, cohort=COHORT_LEGACY) is not None
        )
        if o is not None
    ]

    return {
        "clean_epoch_start": CLEAN_FORWARD_EPOCH_START.isoformat(),
        "clean_epoch_source": CLEAN_EPOCH_SOURCE,
        "legacy_total": LEGACY_FORWARD_COUNT,
        "legacy_affected": LEGACY_AFFECTED_COUNT,
        "legacy_affected_pct": LEGACY_AFFECTED_PCT,
        "legacy_sample_quality": LEGACY_SAMPLE_QUALITY,
        "historical_reference_label": HISTORICAL_COMPROMISED_REFERENCE,
        "new_stamped_count": len(stamped_rows),
        "clean_new_count": len(clean_rows),
        "excluded_invalid_price": excluded_invalid_price,
        "excluded_time_alignment": excluded_alignment,
        "excluded_other_count": len(excluded_rows),
        "legacy_rows": legacy_rows,
        "stamped_rows": stamped_rows,
        "clean_rows": clean_rows,
        "legacy_obs_count": len(legacy_obs),
    }


def assign_clean_forward_obs(rows: Sequence[Any]) -> list[ForwardObs]:
    """Promotion용 CLEAN ForwardObs — quality gate 통과만."""

    out: list[ForwardObs] = []
    for row in rows:
        cls = classify_forward_row(row)
        if not cls.get("clean"):
            continue
        obs = build_forward_obs(row, cohort=COHORT_CLEAN_FORWARD)
        if obs is not None:
            out.append(obs)
    out.sort(key=lambda o: (o.detected_at or datetime.min.replace(tzinfo=timezone.utc), o.shadow_id))
    return out


def count_new_unseen_stamped(rows: Sequence[Any]) -> int:
    """기존 NEW_UNSEEN cohort (backfill 포함) — 참고용."""

    from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
        assign_cohorts,
    )

    obs = assign_cohorts(rows)
    return sum(1 for o in obs if o.cohort == COHORT_NEW)


def evaluate_clean_promotion_gates(
    *,
    clean_n: int,
    baseline: dict[str, Any],
    b1: dict[str, Any],
    early_base: float | None,
    early_b1: float | None,
    stability: dict[str, Any],
    concentration: dict[str, Any],
) -> dict[str, Any]:
    """Promotion gate — CLEAN sample만. Legacy 합산 금지."""

    from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
        NEXT_COLLECT,
        NEXT_REVIEW_FAIL,
        NEXT_REVIEW_PASS,
        VERDICT_COLLECTING,
        VERDICT_GATES_FAILED,
        VERDICT_REVIEW_READY,
    )

    failures: list[str] = []
    gates: dict[str, bool] = {}

    gates["A_clean_ge_500"] = clean_n >= TARGET_CLEAN_MIN
    gates["B_clean_ge_1000_recommended"] = clean_n >= TARGET_CLEAN_RECOMMENDED
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
    gates["K_legacy_excluded_from_promotion"] = True

    for k, ok in gates.items():
        if k == "B_clean_ge_1000_recommended":
            continue  # 권장 — 실패 사유에 넣지 않음
        if not ok:
            failures.append(k)

    sample_ready = gates["A_clean_ge_500"]
    core_pass = all(
        gates[k]
        for k in gates
        if k not in {"B_clean_ge_1000_recommended", "K_legacy_excluded_from_promotion"}
    )

    if not sample_ready:
        verdict = VERDICT_COLLECTING
        next_action = "COLLECT_CLEAN_FORWARD_SAMPLE"
        promo = "NO"
        status = "NOT READY"
    elif core_pass:
        verdict = VERDICT_REVIEW_READY
        next_action = NEXT_REVIEW_PASS
        promo = "NO"
        status = "REVIEW READY"
    else:
        verdict = VERDICT_GATES_FAILED
        next_action = NEXT_REVIEW_FAIL
        promo = "NO"
        status = "NOT READY"

    return {
        "gates": gates,
        "PROMOTION_GATE_FAILURES": failures,
        "all_gates_passed": core_pass and sample_ready,
        "FINAL_VERDICT": verdict,
        "REAL_PROMOTION_RECOMMENDED": promo,
        "PROMOTION_STATUS": status,
        "NEXT_ACTION": next_action,
        "AUTO_PROMOTE": False,
        "promotion_uses_legacy": False,
        "promotion_uses_clean_only": True,
        "note": "Legacy 459 excluded; clean epoch only",
    }


def clean_daily_research_summary(
    clean_obs: Sequence[ForwardObs],
    *,
    partition: dict[str, Any],
    day: Any | None = None,
) -> dict[str, Any]:
    """일일 report — CLEAN KPI만. Legacy와 분리."""

    from datetime import date
    from zoneinfo import ZoneInfo

    from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
        arm_kpi,
        filter_attribution,
    )

    KST = ZoneInfo("Asia/Seoul")
    day = day or date.today()
    today_clean = []
    for o in clean_obs:
        if o.detected_at is None:
            continue
        if o.detected_at.astimezone(KST).date() == day:
            today_clean.append(o)

    base = arm_kpi(clean_obs, eligible="baseline_eligible")
    b1 = arm_kpi(clean_obs, eligible="b1_eligible")
    attr = filter_attribution(clean_obs)
    clean_n = len(clean_obs)

    return {
        "day_kst": day.isoformat() if hasattr(day, "isoformat") else str(day),
        "today_clean_opportunities": len(today_clean),
        "clean_sample_count": clean_n,
        "new_stamped_count": partition.get("new_stamped_count", 0),
        "clean_new_count": partition.get("clean_new_count", 0),
        "excluded_invalid_price": partition.get("excluded_invalid_price", 0),
        "excluded_time_alignment": partition.get("excluded_time_alignment", 0),
        "progress": {
            "clean_min": f"{clean_n} / {TARGET_CLEAN_MIN}",
            "clean_recommended": f"{clean_n} / {TARGET_CLEAN_RECOMMENDED}",
        },
        "baseline_clean": {
            "entries": base.get("entries"),
            "wins": base.get("wins"),
            "losses": base.get("losses"),
            "net": base.get("net_pnl"),
            "pf": base.get("profit_factor"),
            "early_dump_rate": base.get("early_dump_rate"),
        },
        "b1_clean": {
            "entries": b1.get("entries"),
            "wins": b1.get("wins"),
            "losses": b1.get("losses"),
            "net": b1.get("net_pnl"),
            "pf": b1.get("profit_factor"),
            "early_dump_rate": b1.get("early_dump_rate"),
        },
        "filter": attr,
        "legacy_reference": {
            "count": LEGACY_FORWARD_COUNT,
            "affected": LEGACY_AFFECTED_COUNT,
            "affected_pct": LEGACY_AFFECTED_PCT,
            "quality": LEGACY_SAMPLE_QUALITY,
            "label": HISTORICAL_COMPROMISED_REFERENCE,
            "note": "excluded from promotion",
        },
        "REAL_policy_changed": "NO",
        "B1_status": "RESEARCH_ONLY",
    }
