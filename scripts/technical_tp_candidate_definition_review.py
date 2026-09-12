"""READ-ONLY: Discovery cohort TP 2/3/4/6% comparison via compute_tp_sl.

No settings mutation. No DB writes. No candle sync (DB bars only).
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
OUT_JSON = ROOT / "docs" / "audit" / "TECHNICAL_TP_CANDIDATE_DEFINITION_REVIEW.json"


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
        # observation end: last completed bar close in window
        ordered = sorted(
            (b for b in bars if as_utc(detected) <= as_utc(b.candle_at) <= as_utc(terminal)),
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
    capture = None
    if mfe_f is not None and mfe_f > 0:
        capture = ret / mfe_f

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
        "tp_capture_efficiency": capture,
        "bars_checked": (tp_sl.detail or {}).get("bars_checked"),
    }


def main() -> int:
    session = get_session_factory()()
    try:
        rows = list(
            session.scalars(
                select(UpbitOpportunityShadowEntity).where(
                    UpbitOpportunityShadowEntity.deleted_at.is_(None),
                    UpbitOpportunityShadowEntity.status
                    == SHADOW_STATUS_COMPLETED,
                    UpbitOpportunityShadowEntity.shadow_id <= MAX_SHADOW_ID,
                )
            )
        )
        # completed_at cutoff
        discovery = [
            r
            for r in rows
            if r.completed_at is not None and as_utc(r.completed_at) <= CUTOFF
        ]
        strict = [r for r in discovery if _is_valid_cohort_row(r)]

        per_tp: dict[float, dict[str, Any]] = {
            tp: {
                "rows": {},  # shadow_id -> result
                "invalid": 0,
                "missing_bars": 0,
                "ambiguous": 0,
            }
            for tp in TP_SET
        }

        # now far in future so all discovery bars completed
        now = datetime.now(timezone.utc) + timedelta(days=1)

        for row in strict:
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
                    per_tp[tp]["rows"][int(row.shadow_id)] = {
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
                res["shadow_id"] = int(row.shadow_id)
                if res.get("same_candle"):
                    per_tp[tp]["ambiguous"] += 1
                if not res.get("ok"):
                    per_tp[tp]["invalid"] += 1
                per_tp[tp]["rows"][int(row.shadow_id)] = res

        # paired ids: ok for all TP
        ok_sets = [
            {
                sid
                for sid, r in per_tp[tp]["rows"].items()
                if r.get("ok")
            }
            for tp in TP_SET
        ]
        paired_ids = set.intersection(*ok_sets) if ok_sets else set()
        paired_ids = sorted(paired_ids)

        def summarize(tp: float) -> dict[str, Any]:
            rets = [
                float(per_tp[tp]["rows"][sid]["exit_return_pct"])
                for sid in paired_ids
            ]
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
            caps = [
                float(per_tp[tp]["rows"][sid]["tp_capture_efficiency"])
                for sid in paired_ids
                if per_tp[tp]["rows"][sid].get("tp_capture_efficiency")
                is not None
            ]
            tp_hits = sum(
                1 for sid in paired_ids if per_tp[tp]["rows"][sid].get("tp_hit")
            )
            sl_hits = sum(
                1
                for sid in paired_ids
                if per_tp[tp]["rows"][sid].get("exit_kind")
                in {"SL", "SAME_CANDLE_SL_CONSERVATIVE"}
            )
            # first_hit SL means SL exit; also count first_hit TP
            first_tp = sum(
                1
                for sid in paired_ids
                if per_tp[tp]["rows"][sid].get("exit_kind") == "TP"
            )
            timeouts = sum(
                1
                for sid in paired_ids
                if per_tp[tp]["rows"][sid].get("exit_kind") == "TIMEOUT"
            )
            same_c = sum(
                1
                for sid in paired_ids
                if per_tp[tp]["rows"][sid].get("same_candle")
            )
            return {
                "tp_pct": tp,
                "paired_n": len(paired_ids),
                "exit_return": _stats(rets),
                "mfe": _stats(mfes),
                "mae": _stats(maes),
                "tp_capture_efficiency": _stats(caps),
                "tp_hit_count": first_tp,
                "tp_hit_rate": _r(first_tp / len(paired_ids)) if paired_ids else None,
                "sl_exit_count": sl_hits,
                "sl_exit_rate": _r(sl_hits / len(paired_ids)) if paired_ids else None,
                "timeout_count": timeouts,
                "timeout_rate": _r(timeouts / len(paired_ids)) if paired_ids else None,
                "same_candle_ambiguous_n": same_c,
                "raw_tp_flag_count": tp_hits,
                "missing_bars_rows": per_tp[tp]["missing_bars"],
                "invalid_rows": per_tp[tp]["invalid"],
            }

        summaries = {str(tp): summarize(tp) for tp in TP_SET}

        # paired deltas vs 6%
        base = 6.0
        deltas: dict[str, Any] = {}
        for tp in (2.0, 3.0, 4.0):
            row_deltas = []
            for sid in paired_ids:
                a = float(per_tp[tp]["rows"][sid]["exit_return_pct"])
                b = float(per_tp[base]["rows"][sid]["exit_return_pct"])
                row_deltas.append(a - b)
            deltas[str(tp)] = {
                "paired_delta_mean": _r(sum(row_deltas) / len(row_deltas))
                if row_deltas
                else None,
                "paired_delta_median": _r(float(statistics.median(row_deltas)))
                if row_deltas
                else None,
                "delta_mean_return": _r(
                    (summaries[str(tp)]["exit_return"].get("mean") or 0)
                    - (summaries[str(base)]["exit_return"].get("mean") or 0)
                ),
                "delta_median_return": _r(
                    (summaries[str(tp)]["exit_return"].get("median") or 0)
                    - (summaries[str(base)]["exit_return"].get("median") or 0)
                ),
                "delta_positive_rate": _r(
                    (summaries[str(tp)]["exit_return"].get("positive_rate") or 0)
                    - (summaries[str(base)]["exit_return"].get("positive_rate") or 0)
                ),
                "delta_loss_rate": _r(
                    (summaries[str(tp)]["exit_return"].get("loss_rate") or 0)
                    - (summaries[str(base)]["exit_return"].get("loss_rate") or 0)
                ),
                "delta_tp_hit_rate": _r(
                    (summaries[str(tp)].get("tp_hit_rate") or 0)
                    - (summaries[str(base)].get("tp_hit_rate") or 0)
                ),
            }

        # symbol concentration of paired delta for each candidate
        concentration: dict[str, Any] = {}
        for tp in (2.0, 3.0, 4.0):
            by_sym: dict[str, list[float]] = defaultdict(list)
            for sid in paired_ids:
                sym = str(per_tp[tp]["rows"][sid]["symbol"])
                a = float(per_tp[tp]["rows"][sid]["exit_return_pct"])
                b = float(per_tp[base]["rows"][sid]["exit_return_pct"])
                by_sym[sym].append(a - b)
            sym_rows = []
            total_pos = sum(d for d in (x for xs in by_sym.values() for x in xs) if d > 0)
            for sym, ds in sorted(by_sym.items(), key=lambda kv: -sum(kv[1])):
                s = sum(ds)
                sym_rows.append(
                    {
                        "symbol": sym,
                        "n": len(ds),
                        "sum_delta": _r(s),
                        "mean_delta": _r(s / len(ds)),
                    }
                )
            # leave-one-symbol-out on mean paired delta
            overall_mean = (
                sum(
                    float(per_tp[tp]["rows"][sid]["exit_return_pct"])
                    - float(per_tp[base]["rows"][sid]["exit_return_pct"])
                    for sid in paired_ids
                )
                / len(paired_ids)
                if paired_ids
                else 0.0
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
                    - float(per_tp[base]["rows"][sid]["exit_return_pct"])
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
            concentration[str(tp)] = {
                "by_symbol": sym_rows[:12],
                "leave_one_symbol_out": loco,
                "any_sign_flip": any(x["sign_flip_vs_overall"] for x in loco),
            }

        payload = {
            "mode": "READ_ONLY",
            "discovery_cutoff": CUTOFF.isoformat(),
            "max_shadow_id": MAX_SHADOW_ID,
            "baseline_tp_pct": 6.0,
            "candidate_set_pct": [2.0, 3.0, 4.0],
            "sl_pct": SL_PCT,
            "evaluator_policy": "SAME_CANDLE_SL_CONSERVATIVE",
            "candle_source": "market.candle_minute DB only (no sync)",
            "look_ahead_violation": 0,
            "counts": {
                "discovery_completed": len(discovery),
                "strict_valid": len(strict),
                "return_missing_excluded": len(discovery) - len(strict),
                "PAIRED_VALID_N": len(paired_ids),
            },
            "summaries": summaries,
            "deltas_vs_6": deltas,
            "concentration": concentration,
            "paired_shadow_ids": paired_ids,
        }
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"ok": True, "out": str(OUT_JSON), **payload["counts"]}, ensure_ascii=False))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
