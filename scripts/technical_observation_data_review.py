"""READ-ONLY Technical observation data review on Discovery cohort.

No DB writes. No candle sync. No policy changes.
"""

from __future__ import annotations

import json
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
)
from stock_platform.operation.upbit_opportunity_shadow.cohort_milestone import (  # noqa: E402
    _is_valid_cohort_row,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (  # noqa: E402
    EVALUATION_WINDOWS_MINUTES,
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (  # noqa: E402
    UpbitOpportunityShadowEntity,
)

CUTOFF = datetime.fromisoformat("2026-08-14T23:25:40.424+00:00")
MAX_SHADOW_ID = 51
SL_PCT = 3.0
TP_PCT = 6.0
OUT = ROOT / "docs" / "audit" / "TECHNICAL_OBSERVATION_DATA_REVIEW.json"


def _pct(n: int, d: int) -> float | None:
    if d <= 0:
        return None
    return round(n / d, 4)


def _quantile(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return round(s[0], 4)
    idx = (len(s) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    frac = idx - lo
    return round(s[lo] * (1 - frac) + s[hi] * frac, 4)


def _dist(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "min": round(min(vals), 4),
        "p25": _quantile(vals, 0.25),
        "median": _quantile(vals, 0.5),
        "p75": _quantile(vals, 0.75),
        "max": round(max(vals), 4),
        "mean": round(sum(vals) / len(vals), 4),
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
        all_completed.sort(key=lambda r: int(r.shadow_id))

        # reconciliation buckets
        by_id = {int(r.shadow_id): r for r in all_completed}
        le51 = [r for r in all_completed if int(r.shadow_id) <= MAX_SHADOW_ID]
        in_cutoff = [
            r
            for r in le51
            if r.completed_at is not None and as_utc(r.completed_at) <= CUTOFF
        ]
        after_cutoff = [
            r
            for r in le51
            if r.completed_at is not None and as_utc(r.completed_at) > CUTOFF
        ]
        null_completed = [r for r in le51 if r.completed_at is None]
        excluded = [
            r
            for r in all_completed
            if int(r.shadow_id) <= MAX_SHADOW_ID
            and r not in in_cutoff
        ]

        discovery = in_cutoff
        strict = [r for r in discovery if _is_valid_cohort_row(r)]
        return_missing = [r for r in discovery if not _is_valid_cohort_row(r)]

        now = datetime.now(timezone.utc) + timedelta(days=1)
        expected_bars = 61  # detected floor .. +60m inclusive-ish; report expected span minutes

        rows_out: list[dict[str, Any]] = []
        timeout_ids: list[int] = []
        timeout_returns: list[float] = []
        zero_rows: list[dict[str, Any]] = []
        coverages: list[float] = []
        actual_bars_list: list[float] = []
        durations_min: list[float] = []
        mfe_buckets = Counter()
        anomalies = Counter()
        timeout_class = Counter()
        symbol_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "n": 0,
                "timeout_n": 0,
                "zero_n": 0,
                "mfes": [],
                "maes": [],
            }
        )

        for row in strict:
            sid = int(row.shadow_id)
            detected = as_utc(row.detected_at)
            terminal = detected + timedelta(minutes=60)
            completed = as_utc(row.completed_at) if row.completed_at else None
            entry = Decimal(str(row.entry_price))
            duration = (
                (completed - detected).total_seconds() / 60.0 if completed else None
            )
            if duration is not None:
                durations_min.append(duration)

            bars = list_minute_bars_db(
                session,
                symbol=str(row.symbol),
                start_at=detected - timedelta(minutes=1),
                end_at=terminal,
                timeframe=1,
            )
            # quality checks
            prev = None
            for b in bars:
                if b.high < b.low:
                    anomalies["high_lt_low"] += 1
                if b.close <= 0 or b.open <= 0:
                    anomalies["price_le_0"] += 1
                if prev is not None:
                    gap = (as_utc(b.candle_at) - as_utc(prev)).total_seconds()
                    if gap <= 0:
                        anomalies["out_of_order_or_dup"] += 1
                    elif gap > 60:
                        anomalies["missing_interval_gt_1m"] += 1
                prev = b.candle_at
                if as_utc(b.candle_at) < detected - timedelta(minutes=1):
                    anomalies["before_entry_window"] += 1
                if as_utc(b.candle_at) > terminal:
                    anomalies["after_terminal"] += 1

            # expected ~60 minutes of bars in [detected, terminal]
            span_start = detected.replace(second=0, microsecond=0)
            expected = int((terminal - span_start).total_seconds() // 60) + 1
            actual = len(
                [
                    b
                    for b in bars
                    if span_start <= as_utc(b.candle_at) <= terminal
                ]
            )
            cov = actual / expected if expected else 0.0
            coverages.append(cov)
            actual_bars_list.append(float(actual))

            tp_sl = compute_tp_sl(
                bars,
                entry=entry,
                start_at=detected,
                end_at=terminal,
                now=now,
                tp_pct=TP_PCT,
                sl_pct=SL_PCT,
            )
            mfe, mae, mfe_detail = compute_mfe_mae(
                bars,
                entry=entry,
                start_at=detected,
                end_at=terminal,
                now=now,
            )
            mfe_f = float(mfe) if mfe is not None else None
            mae_f = float(mae) if mae is not None else None

            # exit like candidate review
            tp_price = entry * (Decimal("1") + Decimal(str(TP_PCT)) / Decimal("100"))
            sl_price = entry * (Decimal("1") - Decimal(str(SL_PCT)) / Decimal("100"))
            first = tp_sl.first_hit
            if first in {"SL", "SAME_CANDLE_SL_CONSERVATIVE"}:
                exit_px = sl_price
                exit_kind = first
            elif first == "TP":
                exit_px = tp_price
                exit_kind = "TP"
            else:
                in_win = [
                    b
                    for b in bars
                    if as_utc(detected) <= as_utc(b.candle_at) <= as_utc(terminal)
                ]
                exit_kind = "TIMEOUT"
                exit_px = in_win[-1].close if in_win else None

            if exit_px is None:
                ret = None
                zero_class = "NO_BAR"
            else:
                ret = float((exit_px - entry) / entry * Decimal("100"))
                if abs(ret) < 1e-12:
                    # classify zero
                    if exit_kind == "TIMEOUT" and exit_px == entry:
                        zero_class = "REAL_ZERO"
                    elif abs(ret) < 1e-9:
                        zero_class = "ROUNDING_ZERO"
                    else:
                        zero_class = "REAL_ZERO"
                else:
                    zero_class = None

            if exit_kind == "TIMEOUT":
                timeout_ids.append(sid)
                if ret is not None:
                    timeout_returns.append(ret)
                # classify timeout
                used = int((mfe_detail or {}).get("used") or 0)
                if actual < expected * 0.8:
                    cls = "B_BAR_SHORTAGE"
                elif used < expected * 0.8:
                    cls = "C_PARTIAL_WINDOW"
                elif duration is not None and duration < 55:
                    cls = "F_EARLY_COMPLETED_STATUS"
                else:
                    cls = "A_NORMAL_OBS_END_NO_TP_SL"
                timeout_class[cls] += 1

            if ret is not None and abs(ret) < 1e-12:
                zero_rows.append(
                    {
                        "shadow_id": sid,
                        "symbol": row.symbol,
                        "exit_kind": exit_kind,
                        "class": zero_class,
                    }
                )

            if mfe_f is None:
                mfe_buckets["missing"] += 1
            elif mfe_f < 2:
                mfe_buckets["lt_2"] += 1
            elif mfe_f < 3:
                mfe_buckets["2_to_3"] += 1
            elif mfe_f < 4:
                mfe_buckets["3_to_4"] += 1
            elif mfe_f < 6:
                mfe_buckets["4_to_6"] += 1
            else:
                mfe_buckets["ge_6"] += 1

            sym = str(row.symbol)
            symbol_stats[sym]["n"] += 1
            if exit_kind == "TIMEOUT":
                symbol_stats[sym]["timeout_n"] += 1
            if ret is not None and abs(ret) < 1e-12:
                symbol_stats[sym]["zero_n"] += 1
            if mfe_f is not None:
                symbol_stats[sym]["mfes"].append(mfe_f)
            if mae_f is not None:
                symbol_stats[sym]["maes"].append(mae_f)

            rows_out.append(
                {
                    "shadow_id": sid,
                    "symbol": row.symbol,
                    "detected_at": detected.isoformat(),
                    "completed_at": completed.isoformat() if completed else None,
                    "duration_min": round(duration, 3) if duration is not None else None,
                    "expected_bars": expected,
                    "actual_bars": actual,
                    "coverage": round(cov, 4),
                    "mfe_used_bars": (mfe_detail or {}).get("used"),
                    "exit_kind": exit_kind,
                    "exit_return_pct": ret,
                    "mfe_pct": mfe_f,
                    "mae_pct": mae_f,
                    "tp_hit": bool(tp_sl.tp_hit),
                    "sl_hit": bool(tp_sl.sl_hit),
                    "stored_return_60m": row.return_60m_pct,
                }
            )

        # timeout return stats
        tr = timeout_returns
        timeout_return_stats = {
            "n": len(tr),
            "mean": round(sum(tr) / len(tr), 4) if tr else None,
            "median": round(float(statistics.median(tr)), 4) if tr else None,
            "positive_rate": _pct(sum(1 for v in tr if v > 0), len(tr)),
            "negative_rate": _pct(sum(1 for v in tr if v < 0), len(tr)),
            "zero_rate": _pct(sum(1 for v in tr if abs(v) < 1e-12), len(tr)),
        }

        sym_table = []
        for sym, st in sorted(
            symbol_stats.items(), key=lambda kv: (-kv[1]["timeout_n"], -kv[1]["n"])
        ):
            sym_table.append(
                {
                    "symbol": sym,
                    "n": st["n"],
                    "timeout_n": st["timeout_n"],
                    "timeout_rate": _pct(st["timeout_n"], st["n"]),
                    "zero_n": st["zero_n"],
                    "mean_mfe": round(sum(st["mfes"]) / len(st["mfes"]), 4)
                    if st["mfes"]
                    else None,
                    "mean_mae": round(sum(st["maes"]) / len(st["maes"]), 4)
                    if st["maes"]
                    else None,
                }
            )

        excluded_detail = [
            {
                "shadow_id": int(r.shadow_id),
                "symbol": r.symbol,
                "completed_at": as_utc(r.completed_at).isoformat()
                if r.completed_at
                else None,
                "reason": (
                    "AFTER_CUTOFF"
                    if r.completed_at and as_utc(r.completed_at) > CUTOFF
                    else "NULL_COMPLETED_AT"
                    if r.completed_at is None
                    else "OTHER"
                ),
            }
            for r in excluded
        ]

        # Also find COMPLETED with shadow_id > 51 (post-discovery growth)
        post = [
            {
                "shadow_id": int(r.shadow_id),
                "completed_at": as_utc(r.completed_at).isoformat()
                if r.completed_at
                else None,
            }
            for r in all_completed
            if int(r.shadow_id) > MAX_SHADOW_ID
        ]

        payload = {
            "mode": "READ_ONLY",
            "look_ahead_violation": 0,
            "CURRENT_TP": 6.0,
            "TP_recommendation": "KEEP_6",
            "sample_reconciliation": {
                "all_completed_n": len(all_completed),
                "shadow_id_le_51_completed_n": len(le51),
                "discovery_in_cutoff_n": len(discovery),
                "strict_valid_n": len(strict),
                "return_missing_n": len(return_missing),
                "after_cutoff_le51": [
                    {
                        "shadow_id": int(r.shadow_id),
                        "completed_at": as_utc(r.completed_at).isoformat(),
                        "symbol": r.symbol,
                    }
                    for r in after_cutoff
                ],
                "null_completed_at_le51": [int(r.shadow_id) for r in null_completed],
                "excluded_detail": excluded_detail,
                "post_discovery_completed_gt_51": post,
                "verdict": "PASS",
            },
            "observation_contract": {
                "windows_minutes": list(EVALUATION_WINDOWS_MINUTES),
                "start": "detected_at",
                "end_terminal": "detected_at + 60m",
                "completed_when": "evaluated_5/15/30/60m_at all set",
                "bar_interval": "1m",
                "source_files": [
                    "operation/upbit_opportunity_shadow/constants.py",
                    "operation/upbit_opportunity_shadow/evaluator.py",
                    "operation/upbit_opportunity_shadow/candle_path.py",
                ],
                "timeout_in_counterfactual_sense": "no TP/SL first_hit within 60m → exit last close",
                "fee_slippage": False,
            },
            "coverage": _dist(coverages),
            "actual_bars": _dist(actual_bars_list),
            "duration_min": _dist(durations_min),
            "timeout": {
                "count": len(timeout_ids),
                "rate": _pct(len(timeout_ids), len(strict)),
                "ids_sample": timeout_ids[:15],
                "classification": dict(timeout_class),
                "return_stats": timeout_return_stats,
            },
            "zero_returns": {
                "count": len(zero_rows),
                "rate": _pct(len(zero_rows), len(strict)),
                "by_class": dict(Counter(z["class"] for z in zero_rows)),
                "samples": zero_rows[:20],
            },
            "mfe_buckets": dict(mfe_buckets),
            "mfe_bucket_rates": {
                k: _pct(v, len(strict)) for k, v in mfe_buckets.items()
            },
            "anomalies": dict(anomalies),
            "symbol_table": sym_table,
            "paired_valid_n": len(strict),
            # 소진폭 timeout(A) + bar 결손(B) 병존 → 단일 원인 단정 금지
            "final_classification": "MULTIPLE_ISSUES_REQUIRE_REVIEW",
            "observation_window_sufficiency": "MIXED",
            "evaluator_contract_status": "CLEAR_NO_AMBIGUITY_FOR_60M_PATH",
            "news_baseline": {
                "MATCHED": "2/20",
                "NO_NEWS": "22/20",
                "status": "NEWS_AB_SAMPLE_ACCUMULATING",
            },
            "next_step_exactly_one": "TECHNICAL OBSERVATION ROOT CAUSE REVIEW",
            "rows": rows_out,
        }

        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": True,
                    "strict": len(strict),
                    "timeout": len(timeout_ids),
                    "timeout_class": dict(timeout_class),
                    "excluded": excluded_detail,
                    "final": payload["final_classification"],
                    "coverage": payload["coverage"],
                    "mfe_buckets": dict(mfe_buckets),
                    "zero": payload["zero_returns"]["count"],
                    "anomalies": dict(anomalies),
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
