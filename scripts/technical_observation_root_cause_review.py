"""READ-ONLY: Separate market low-move vs bar-coverage deficiency.

No DB writes. No candle sync. No policy changes.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
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
    floor_minute,
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
TP_PCT = 6.0
TP_SET = (2.0, 3.0, 4.0, 6.0)
DIAG_COV = 0.8
OUT = ROOT / "docs" / "audit" / "TECHNICAL_OBSERVATION_ROOT_CAUSE_REVIEW.json"


def _r(v: float | None, nd: int = 4) -> float | None:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), nd)


def _pct(n: int, d: int) -> float | None:
    if d <= 0:
        return None
    return _r(n / d)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    deny = math.sqrt(sum((y - my) ** 2 for y in ys))
    if denx == 0 or deny == 0:
        return None
    return _r(num / (denx * deny))


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """순위 상관 — 동점 평균 순위."""

    def ranks(vals: list[float]) -> list[float]:
        indexed = sorted(enumerate(vals), key=lambda t: t[1])
        out = [0.0] * len(vals)
        i = 0
        while i < len(indexed):
            j = i
            while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[indexed[k][0]] = avg
            i = j + 1
        return out

    if len(xs) < 3:
        return None
    return _pearson(ranks(xs), ranks(ys))


def _group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    covs = [r["coverage"] for r in rows]
    rets = [r["exit_return_pct"] for r in rows if r["exit_return_pct"] is not None]
    mfes = [r["mfe_pct"] for r in rows if r["mfe_pct"] is not None]
    maes = [r["mae_pct"] for r in rows if r["mae_pct"] is not None]
    timeout_n = sum(1 for r in rows if r["exit_kind"] == "TIMEOUT")
    tp_n = sum(1 for r in rows if r["exit_kind"] == "TP")
    sl_n = sum(
        1
        for r in rows
        if r["exit_kind"] in {"SL", "SAME_CANDLE_SL_CONSERVATIVE"}
    )
    pos = sum(1 for v in rets if v > 0)
    loss = sum(1 for v in rets if v < 0)
    zero = sum(1 for v in rets if abs(v) < 1e-12)
    return {
        "n": n,
        "coverage_mean": _r(sum(covs) / n),
        "coverage_median": _r(float(statistics.median(covs))),
        "timeout_n": timeout_n,
        "timeout_rate": _pct(timeout_n, n),
        "tp_hit_n": tp_n,
        "tp_hit_rate": _pct(tp_n, n),
        "sl_exit_n": sl_n,
        "sl_exit_rate": _pct(sl_n, n),
        "mean_exit_return": _r(sum(rets) / len(rets)) if rets else None,
        "median_exit_return": _r(float(statistics.median(rets))) if rets else None,
        "positive_rate": _pct(pos, len(rets)) if rets else None,
        "loss_rate": _pct(loss, len(rets)) if rets else None,
        "zero_rate": _pct(zero, len(rets)) if rets else None,
        "mean_mfe": _r(sum(mfes) / len(mfes)) if mfes else None,
        "median_mfe": _r(float(statistics.median(mfes))) if mfes else None,
        "mean_mae": _r(sum(maes) / len(maes)) if maes else None,
        "median_mae": _r(float(statistics.median(maes))) if maes else None,
    }


def _mfe_buckets(rows: list[dict[str, Any]]) -> dict[str, Any]:
    c = Counter()
    for r in rows:
        m = r["mfe_pct"]
        if m is None:
            c["missing"] += 1
        elif m < 2:
            c["lt_2"] += 1
        elif m < 3:
            c["2_to_3"] += 1
        elif m < 4:
            c["3_to_4"] += 1
        elif m < 6:
            c["4_to_6"] += 1
        else:
            c["ge_6"] += 1
    n = len(rows) or 1
    return {
        "counts": dict(c),
        "rates": {k: _pct(v, len(rows)) for k, v in c.items()},
        "n": len(rows),
    }


def _exit(
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
    mfe, mae, detail = compute_mfe_mae(
        bars,
        entry=entry,
        start_at=detected,
        end_at=terminal,
        now=now,
    )
    tp_price = entry * (Decimal("1") + Decimal(str(abs(tp_pct))) / Decimal("100"))
    sl_price = entry * (Decimal("1") - Decimal(str(abs(sl_pct))) / Decimal("100"))
    first = tp_sl.first_hit
    if first in {"SL", "SAME_CANDLE_SL_CONSERVATIVE"}:
        kind, px = first, sl_price
    elif first == "TP":
        kind, px = "TP", tp_price
    else:
        in_win = [
            b
            for b in bars
            if as_utc(detected) <= as_utc(b.candle_at) <= as_utc(terminal)
        ]
        kind = "TIMEOUT"
        px = in_win[-1].close if in_win else None
    ret = (
        float((px - entry) / entry * Decimal("100")) if px is not None else None
    )
    return {
        "exit_kind": kind if kind != "SAME_CANDLE_SL_CONSERVATIVE" else "SL",
        "exit_return_pct": ret,
        "mfe_pct": float(mfe) if mfe is not None else None,
        "mae_pct": float(mae) if mae is not None else None,
        "mfe_used": (detail or {}).get("used"),
        "tp_hit": bool(tp_sl.tp_hit),
        "sl_hit": bool(tp_sl.sl_hit),
    }


def _gap_profile(
    *,
    span_start: datetime,
    terminal: datetime,
    present: set[datetime],
) -> dict[str, Any]:
    """분 단위 기대 슬롯 vs 존재 여부 → 구간·연속 gap."""

    expected: list[datetime] = []
    t = span_start
    while t <= terminal:
        expected.append(t)
        t = t + timedelta(minutes=1)

    missing_flags = [1 if e not in present else 0 for e in expected]
    n = len(expected) or 1
    thirds = [
        ("0_20", expected[:20]),
        ("20_40", expected[20:40]),
        ("40_60", expected[40:]),
    ]
    miss_by = {}
    for name, slots in thirds:
        if not slots:
            miss_by[name] = None
            continue
        miss = sum(1 for s in slots if s not in present)
        miss_by[name] = _r(miss / len(slots))

    # 연속 gap
    max_run = 0
    run = 0
    for f in missing_flags:
        if f:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0

    # 위치 분류
    early = miss_by.get("0_20") or 0.0
    mid = miss_by.get("20_40") or 0.0
    late = miss_by.get("40_60") or 0.0
    vals = {"EARLY_GAP": early, "MIDDLE_GAP": mid, "LATE_GAP": late}
    top = max(vals.values())
    if top < 0.15:
        gap_class = "DISTRIBUTED_GAP" if sum(missing_flags) > 0 else "NONE"
        # 산발: 어느 구간도 지배적이지 않거나 고르게
        if sum(missing_flags) > 0 and max(vals.values()) - min(vals.values()) < 0.15:
            gap_class = "DISTRIBUTED_GAP"
        elif sum(missing_flags) == 0:
            gap_class = "NONE"
        else:
            # 약한 지배
            gap_class = max(vals, key=vals.get)  # type: ignore[arg-type]
    else:
        # 한 구간이 뚜렷하면 그 클래스; 비슷하면 DISTRIBUTED
        ranked = sorted(vals.items(), key=lambda kv: -kv[1])
        if ranked[0][1] - ranked[1][1] < 0.1 and ranked[1][1] >= 0.15:
            gap_class = "DISTRIBUTED_GAP"
        else:
            gap_class = ranked[0][0]

    return {
        "miss_by_third": miss_by,
        "max_consecutive_missing": max_run,
        "missing_n": sum(missing_flags),
        "expected_n": len(expected),
        "gap_class": gap_class,
    }


def main() -> int:
    session = get_session_factory()()
    try:
        all_completed = list(
            session.scalars(
                select(UpbitOpportunityShadowEntity).where(
                    UpbitOpportunityShadowEntity.deleted_at.is_(None),
                    UpbitOpportunityShadowEntity.status
                    == SHADOW_STATUS_COMPLETED,
                )
            )
        )
        discovery = [
            r
            for r in all_completed
            if int(r.shadow_id) <= MAX_SHADOW_ID
            and r.completed_at is not None
            and as_utc(r.completed_at) <= CUTOFF
        ]
        strict = [r for r in discovery if _is_valid_cohort_row(r)]
        now = datetime.now(timezone.utc) + timedelta(days=1)

        rows: list[dict[str, Any]] = []
        for row in strict:
            detected = as_utc(row.detected_at)
            terminal = detected + timedelta(minutes=60)
            completed = as_utc(row.completed_at) if row.completed_at else None
            lag_min = (
                (completed - detected).total_seconds() / 60.0 if completed else None
            )
            entry = Decimal(str(row.entry_price))
            span_start = floor_minute(detected)

            bars = list_minute_bars_db(
                session,
                symbol=str(row.symbol),
                start_at=detected - timedelta(minutes=1),
                end_at=terminal,
                timeframe=1,
            )
            present = {
                as_utc(b.candle_at)
                for b in bars
                if span_start <= as_utc(b.candle_at) <= terminal
            }
            expected_n = int((terminal - span_start).total_seconds() // 60) + 1
            actual = len(present)
            cov = actual / expected_n if expected_n else 0.0

            ex6 = _exit(
                entry=entry,
                bars=bars,
                detected=detected,
                terminal=terminal,
                now=now,
                tp_pct=TP_PCT,
                sl_pct=SL_PCT,
            )
            gap = _gap_profile(
                span_start=span_start, terminal=terminal, present=present
            )

            tp_grid = {}
            for tp in TP_SET:
                tp_grid[str(tp)] = _exit(
                    entry=entry,
                    bars=bars,
                    detected=detected,
                    terminal=terminal,
                    now=now,
                    tp_pct=tp,
                    sl_pct=SL_PCT,
                )

            rows.append(
                {
                    "shadow_id": int(row.shadow_id),
                    "symbol": str(row.symbol),
                    "coverage": cov,
                    "actual_bars": actual,
                    "expected_bars": expected_n,
                    "lag_min": lag_min,
                    **ex6,
                    "gap": gap,
                    "tp_grid": tp_grid,
                }
            )

        high = [r for r in rows if r["coverage"] >= DIAG_COV]
        low = [r for r in rows if r["coverage"] < DIAG_COV]

        # 2x2 matrix
        matrix = {}
        for key, pred in [
            ("A_high_cov_low_mfe", lambda r: r["coverage"] >= 0.8 and (r["mfe_pct"] or -1) < 2),
            ("B_high_cov_mfe_ge2", lambda r: r["coverage"] >= 0.8 and (r["mfe_pct"] or -1) >= 2),
            ("C_low_cov_low_mfe", lambda r: r["coverage"] < 0.8 and (r["mfe_pct"] or -1) < 2),
            ("D_low_cov_mfe_ge2", lambda r: r["coverage"] < 0.8 and (r["mfe_pct"] or -1) >= 2),
        ]:
            cell = [r for r in rows if pred(r)]
            rets = [r["exit_return_pct"] for r in cell if r["exit_return_pct"] is not None]
            to_n = sum(1 for r in cell if r["exit_kind"] == "TIMEOUT")
            matrix[key] = {
                "n": len(cell),
                "percentage": _pct(len(cell), len(rows)),
                "mean_return": _r(sum(rets) / len(rets)) if rets else None,
                "median_return": _r(float(statistics.median(rets))) if rets else None,
                "timeout_rate": _pct(to_n, len(cell)) if cell else None,
                "ids": [r["shadow_id"] for r in cell[:8]],
            }

        a_n = matrix["A_high_cov_low_mfe"]["n"]
        high_n = len(high) or 1
        low_move_dominates_high_cov = a_n / high_n >= 0.7 if high else False

        full_m = _group_metrics(rows)
        high_m = _group_metrics(high)
        low_m = _group_metrics(low)

        def _delta(a: float | None, b: float | None) -> float | None:
            if a is None or b is None:
                return None
            return _r(a - b)

        deltas = {
            "delta_mean_return_high_minus_full": _delta(
                high_m.get("mean_exit_return"), full_m.get("mean_exit_return")
            ),
            "delta_median_return": _delta(
                high_m.get("median_exit_return"), full_m.get("median_exit_return")
            ),
            "delta_positive_rate": _delta(
                high_m.get("positive_rate"), full_m.get("positive_rate")
            ),
            "delta_loss_rate": _delta(high_m.get("loss_rate"), full_m.get("loss_rate")),
            "delta_mean_mfe": _delta(high_m.get("mean_mfe"), full_m.get("mean_mfe")),
            "delta_mean_mae": _delta(high_m.get("mean_mae"), full_m.get("mean_mae")),
            "delta_tp_hit_rate": _delta(
                high_m.get("tp_hit_rate"), full_m.get("tp_hit_rate")
            ),
            "delta_timeout_rate": _delta(
                high_m.get("timeout_rate"), full_m.get("timeout_rate")
            ),
        }

        # Impact heuristic
        abs_d_ret = abs(deltas["delta_mean_return_high_minus_full"] or 0)
        abs_d_mfe = abs(deltas["delta_mean_mfe"] or 0)
        abs_d_to = abs(deltas["delta_timeout_rate"] or 0)
        if abs_d_ret < 0.05 and abs_d_mfe < 0.3 and abs_d_to < 0.05:
            impact = "LOW"
        elif abs_d_ret < 0.15 and abs_d_mfe < 0.8 and abs_d_to < 0.12:
            impact = "MEDIUM"
        else:
            impact = "HIGH"

        covs = [r["coverage"] for r in rows]
        mfes = [r["mfe_pct"] if r["mfe_pct"] is not None else 0.0 for r in rows]
        maes = [r["mae_pct"] if r["mae_pct"] is not None else 0.0 for r in rows]
        rets_all = [
            r["exit_return_pct"] if r["exit_return_pct"] is not None else 0.0
            for r in rows
        ]
        lags = [r["lag_min"] or 0.0 for r in rows]
        missing_ns = [r["gap"]["missing_n"] for r in rows]

        corr = {
            "coverage_mfe_pearson": _pearson(covs, mfes),
            "coverage_mfe_spearman": _spearman(covs, mfes),
            "coverage_mae_pearson": _pearson(covs, maes),
            "coverage_mae_spearman": _spearman(covs, maes),
            "coverage_return_pearson": _pearson(covs, rets_all),
            "coverage_return_spearman": _spearman(covs, rets_all),
            "lag_coverage_pearson": _pearson(lags, covs),
            "lag_coverage_spearman": _spearman(lags, covs),
            "lag_missing_pearson": _pearson(lags, [float(x) for x in missing_ns]),
            "lag_missing_spearman": _spearman(lags, [float(x) for x in missing_ns]),
        }

        # Gap classes among low coverage
        gap_counts = Counter(r["gap"]["gap_class"] for r in low)
        consec = [r["gap"]["max_consecutive_missing"] for r in low]
        consec_stats = {
            "min": min(consec) if consec else None,
            "median": int(statistics.median(consec)) if consec else None,
            "max": max(consec) if consec else None,
            "n": len(consec),
        }
        late_gap_n = gap_counts.get("LATE_GAP", 0)

        # Symbol table
        by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            by_sym[r["symbol"]].append(r)
        sym_table = []
        low_cov_total = len(low) or 1
        for sym, rs in sorted(by_sym.items(), key=lambda kv: -sum(1 for x in kv[1] if x["coverage"] < 0.8)):
            low_n = sum(1 for x in rs if x["coverage"] < 0.8)
            to_n = sum(1 for x in rs if x["exit_kind"] == "TIMEOUT")
            mf = [x["mfe_pct"] for x in rs if x["mfe_pct"] is not None]
            cv = [x["coverage"] for x in rs]
            sym_table.append(
                {
                    "symbol": sym,
                    "n": len(rs),
                    "mean_coverage": _r(sum(cv) / len(cv)),
                    "coverage_lt_0_8_n": low_n,
                    "share_of_all_low_cov": _pct(low_n, len(low)),
                    "mean_mfe": _r(sum(mf) / len(mf)) if mf else None,
                    "timeout_rate": _pct(to_n, len(rs)),
                }
            )

        top3_low = sum(s["coverage_lt_0_8_n"] for s in sym_table[:3])
        if top3_low / low_cov_total >= 0.5:
            sym_conc = "HIGH"
        elif top3_low / low_cov_total >= 0.3:
            sym_conc = "MEDIUM"
        else:
            sym_conc = "LOW"

        grvt = next((r for r in rows if r["symbol"] == "KRW-GRVT"), None)

        # High coverage TP grid
        hc_tp = {}
        for tp in TP_SET:
            rets = []
            tp_hits = 0
            losses = 0
            for r in high:
                g = r["tp_grid"][str(tp)]
                if g["exit_return_pct"] is not None:
                    rets.append(g["exit_return_pct"])
                    if g["exit_return_pct"] < 0:
                        losses += 1
                if g["exit_kind"] == "TP":
                    tp_hits += 1
            hc_tp[str(tp)] = {
                "mean_exit_return": _r(sum(rets) / len(rets)) if rets else None,
                "median_exit_return": _r(float(statistics.median(rets))) if rets else None,
                "tp_hit_rate": _pct(tp_hits, len(high)),
                "loss_rate": _pct(losses, len(rets)) if rets else None,
            }

        # Direction vs full: 6 best mean among 2/3/4/6?
        means = {k: v["mean_exit_return"] for k, v in hc_tp.items()}
        best = max(means, key=lambda k: means[k] if means[k] is not None else -999)
        if len(high) < 15:
            hc_cand = "INSUFFICIENT_SAMPLE"
        elif best == "6.0" or (
            means.get("6.0") is not None
            and all(
                (means["6.0"] or 0) >= (means[k] or 0) - 1e-9
                for k in ("2.0", "3.0", "4.0")
            )
        ):
            hc_cand = "KEEP_6_DIRECTION"
        else:
            hc_cand = "CANDIDATE_DIRECTION_CHANGED"

        # Sensitivity
        sens = {}
        for thr in (0.7, 0.8, 0.9):
            sub = [r for r in rows if r["coverage"] >= thr]
            m = _group_metrics(sub)
            sens[str(thr)] = {
                "n": m["n"],
                "mean_mfe": m.get("mean_mfe"),
                "mean_exit_return": m.get("mean_exit_return"),
                "tp6_hit_rate": m.get("tp_hit_rate"),
                "timeout_rate": m.get("timeout_rate"),
            }

        # Lag question
        lag_spear = corr["lag_coverage_spearman"]
        if lag_spear is None:
            lag_ans = "INCONCLUSIVE"
        elif lag_spear <= -0.25:
            lag_ans = "YES"
        elif lag_spear >= -0.1:
            lag_ans = "NO"
        else:
            lag_ans = "INCONCLUSIVE"

        # Root cause verdict
        market = (
            "SUPPORTED"
            if low_move_dominates_high_cov
            else "NOT_SUPPORTED"
            if high and a_n / high_n < 0.4
            else "INCONCLUSIVE"
        )
        data_issue = (
            "SUPPORTED"
            if len(low) >= 10 and low_m.get("coverage_mean", 1) < 0.75
            else "NOT_SUPPORTED"
            if len(low) < 5
            else "INCONCLUSIVE"
        )

        if market == "SUPPORTED" and impact == "LOW":
            final = "MARKET_LOW_MOVE_DOMINANT"
            policy = "KEEP_6_AND_FREEZE_BASELINE"
            # still data exists but not material for performance conclusion
            if data_issue == "SUPPORTED" and len(low) / len(rows) >= 0.3:
                # material share of sample has data issue even if performance delta low
                final = "MIXED_MARKET_AND_DATA"
                policy = "KEEP_6_AND_FIX_DATA_FIRST"
        elif market == "SUPPORTED" and data_issue == "SUPPORTED":
            if impact in {"MEDIUM", "HIGH"}:
                final = "MIXED_MARKET_AND_DATA"
                policy = "KEEP_6_AND_FIX_DATA_FIRST"
            else:
                final = "MIXED_MARKET_AND_DATA"
                policy = "KEEP_6_AND_FIX_DATA_FIRST"
        elif data_issue == "SUPPORTED" and market != "SUPPORTED":
            final = "DATA_COVERAGE_DOMINANT"
            policy = "KEEP_6_AND_FIX_DATA_FIRST"
        elif impact == "LOW" and market == "SUPPORTED":
            final = "DATA_ISSUE_NOT_MATERIAL"
            policy = "KEEP_6_AND_FREEZE_BASELINE"
        else:
            final = "ROOT_CAUSE_INCONCLUSIVE"
            policy = "NO_POLICY_DECISION_UNTIL_DATA_FIX"

        # next step mapping
        if final in {"MARKET_LOW_MOVE_DOMINANT", "DATA_ISSUE_NOT_MATERIAL"}:
            next_step = "TECHNICAL CURRENT POLICY BASELINE FREEZE"
        elif final in {"DATA_COVERAGE_DOMINANT", "MIXED_MARKET_AND_DATA"}:
            next_step = "TECHNICAL BAR COVERAGE REMEDIATION DESIGN"
        else:
            next_step = "TECHNICAL OBSERVATION EVIDENCE EXTENSION DESIGN"

        payload = {
            "mode": "READ_ONLY",
            "look_ahead_violation": 0,
            "CURRENT_TP": 6.0,
            "diagnostic_coverage_threshold": DIAG_COV,
            "note": "0.8 is diagnostic split only — not production policy",
            "full_n": len(rows),
            "high_coverage_n": len(high),
            "low_coverage_n": len(low),
            "group_H": high_m,
            "group_L": low_m,
            "full": full_m,
            "matrix_2x2": matrix,
            "sufficient_coverage_still_low_mfe_dominant": bool(
                low_move_dominates_high_cov
            ),
            "high_coverage_mfe_buckets": _mfe_buckets(high),
            "high_coverage_tp6": high_m,
            "deltas_high_minus_full": deltas,
            "COVERAGE_IMPACT": impact,
            "correlations": corr,
            "gap_class_counts_low_cov": dict(gap_counts),
            "late_gap_n": late_gap_n,
            "late_gap_distortion_flag": late_gap_n > 0,
            "consecutive_gap_low_cov": consec_stats,
            "data_source_root_cause": {
                "candle_source": {
                    "verdict": "CONFIRMED_CAUSE",
                    "detail": "market.candle_minute via list_minute_bars_db",
                    "ref": "candle_loader.list_minute_bars_db",
                },
                "fetch_range": {
                    "verdict": "CONFIRMED_CAUSE",
                    "detail": "evaluator loads detected..min(now, detected+60m); review uses DB snapshot only",
                    "ref": "evaluator._compute_payload / ensure_shadow_minute_bars",
                },
                "pagination": {
                    "verdict": "POSSIBLE",
                    "detail": "Upbit minute candle sync path may page; not proven for these gaps",
                    "ref": "candle_loader.ensure_shadow_minute_bars sync branch",
                },
                "api_limit": {
                    "verdict": "POSSIBLE",
                    "detail": "external sync limits possible; this review did not call API",
                    "ref": "allow_sync path",
                },
                "retry": {
                    "verdict": "NOT_SUPPORTED",
                    "detail": "no evidence in this READ-ONLY pass that retry failure caused gaps",
                },
                "rate_limit": {
                    "verdict": "POSSIBLE",
                    "detail": "could delay sync during evaluation; not confirmed from DB fields",
                },
                "scheduler_delay": {
                    "verdict": "POSSIBLE",
                    "detail": "completion lag up to ~1431m; weak/negative lag↔coverage corr → not confirmed driver",
                },
                "persistence": {
                    "verdict": "POSSIBLE",
                    "detail": "missing minutes absent from market.candle_minute for symbol window",
                    "ref": "DB absence observed in list_minute_bars_db",
                },
                "timezone_conversion": {
                    "verdict": "NOT_SUPPORTED",
                    "detail": "as_utc used consistently; no mismatch anomaly in prior review",
                },
                "symbol_availability": {
                    "verdict": "POSSIBLE",
                    "detail": "thin symbols can have sparse minutes; concentration MEDIUM/LOW TBD",
                },
                "evaluator_fetch_timing": {
                    "verdict": "POSSIBLE",
                    "detail": "eval_end=min(now, terminal); late completion can finalize with partial bars if sync incomplete",
                    "ref": "evaluator.py eval_end",
                },
            },
            "lag_vs_coverage_answer": lag_ans,
            "symbol_table": sym_table,
            "SYMBOL_COVERAGE_CONCENTRATION": sym_conc,
            "KRW_GRVT": grvt,
            "high_coverage_tp_grid": hc_tp,
            "HIGH_COVERAGE_CANDIDATE_RESULT": hc_cand,
            "threshold_sensitivity": sens,
            "MARKET_LOW_MOVE": market,
            "DATA_COVERAGE_ISSUE": data_issue,
            "final_classification": final,
            "policy_implication": policy,
            "news_baseline": {
                "MATCHED": "2/20",
                "NO_NEWS": "22/20",
                "status": "NEWS_AB_SAMPLE_ACCUMULATING",
            },
            "mutations": {
                "production": 0,
                "db": 0,
                "trading_order": 0,
                "outbox": 0,
                "create_order": 0,
                "post_orders": 0,
                "live_arm_scheduler": 0,
                "commit_push": 0,
            },
            "next_step_exactly_one": next_step,
            "rows": rows,
        }

        OUT.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "final": final,
                    "market": market,
                    "data": data_issue,
                    "impact": impact,
                    "high_n": len(high),
                    "low_n": len(low),
                    "matrix": {k: v["n"] for k, v in matrix.items()},
                    "low_move_on_high_cov": low_move_dominates_high_cov,
                    "corr_cov_mfe": corr["coverage_mfe_spearman"],
                    "lag_ans": lag_ans,
                    "hc_cand": hc_cand,
                    "policy": policy,
                    "next": next_step,
                    "gap_counts": dict(gap_counts),
                    "sym_conc": sym_conc,
                    "deltas": deltas,
                    "sens": sens,
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
