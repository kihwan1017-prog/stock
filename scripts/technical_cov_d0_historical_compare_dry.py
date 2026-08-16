"""COV-D0 READ-ONLY historical backfill/compare dry.

- No DB UPDATE/INSERT/DELETE
- Source range GET allowed; persist_upsert=False
- Writes audit JSON only
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import timedelta
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
    observe_windows,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (  # noqa: E402
    EVALUATION_WINDOWS_MINUTES,
    SHADOW_STATUS_ACTIVE,
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (  # noqa: E402
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.path_quality import (  # noqa: E402
    PATH_QUALITY_VERSION,
    compute_path_quality,
    path_completeness_pass,
)
from stock_platform.operation.upbit_opportunity_shadow.source_range_reconcile import (  # noqa: E402
    reconcile_observation_source,
)

OUT = ROOT / "docs" / "audit" / "TECHNICAL_COV_D0_HISTORICAL_COMPARE_PRECHECK.json"
OUT_MD = ROOT / "docs" / "audit" / "TECHNICAL_COV_D0_HISTORICAL_COMPARE_PRECHECK.md"
TP_PCT = 6.0
SL_PCT = 3.0
EPS = 1e-6


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cmp(a: float | None, b: float | None) -> str:
    if a is None and b is None:
        return "SAME"
    if a is None or b is None:
        return "NOT_COMPARABLE"
    if abs(a - b) <= max(EPS, abs(a) * 1e-9):
        return "SAME"
    return "CHANGED"


def _bool_cmp(a: bool | None, b: bool | None) -> str:
    if a is None and b is None:
        return "SAME"
    if a is None or b is None:
        return "NOT_COMPARABLE"
    return "SAME" if bool(a) == bool(b) else "CHANGED"


async def _process_row(session, row: UpbitOpportunityShadowEntity) -> dict[str, Any]:
    detected = as_utc(row.detected_at)
    terminal = detected + timedelta(minutes=60)
    now = as_utc(row.evaluated_60m_at or row.completed_at or terminal)
    entry = row.entry_price
    if entry is None:
        return {
            "shadow_id": row.shadow_id,
            "symbol": row.symbol,
            "reconstructable": False,
            "reason": "NO_ENTRY_PRICE",
        }

    bars = list_minute_bars_db(
        session,
        symbol=str(row.symbol),
        start_at=detected - timedelta(minutes=2),
        end_at=terminal + timedelta(minutes=2),
        timeframe=1,
    )
    # GET only — no upsert
    bars2, evidence = await reconcile_observation_source(
        session,
        symbol=str(row.symbol),
        detected_at=detected,
        terminal_at=terminal,
        now=now,
        bars=bars,
        timeframe=1,
        allow_sync=True,
        persist_upsert=False,
    )
    pq = compute_path_quality(
        detected_at=detected,
        end_at=terminal,
        now=now,
        bars=bars2,
        source_absent_confirmed_ats=evidence.absent_ats(),
        source_unavailable=bool(evidence.source_unavailable),
        sync_attempts=0,
        sync_last_result=evidence.source_check_result,
        source_check_performed=evidence.source_check_performed,
        source_check_result=evidence.source_check_result,
        source_candle_count=evidence.source_candle_count,
        db_missing_source_present=len(evidence.db_missing_source_present_ats),
        source_reconcile_requests=evidence.requests,
    )
    pq_d = pq.to_detail_dict() if hasattr(pq, "to_detail_dict") else dict(pq)

    obs = observe_windows(
        bars2,
        detected_at=detected,
        entry=entry,
        now=now,
        windows_minutes=EVALUATION_WINDOWS_MINUTES,
    )
    windows = {str(o.minutes): o for o in obs}
    mfe, mae, _ = compute_mfe_mae(
        bars2, entry=entry, start_at=detected, end_at=terminal, now=now
    )
    tp_sl = compute_tp_sl(
        bars2,
        entry=entry,
        start_at=detected,
        end_at=terminal,
        now=now,
        tp_pct=TP_PCT,
        sl_pct=SL_PCT,
    )
    # TpSlResult dataclass (dict 아님)
    tp_hit_v = bool(getattr(tp_sl, "tp_hit", False))
    sl_hit_v = bool(getattr(tp_sl, "sl_hit", False))

    def _win_ret(minutes: int) -> float | None:
        o = windows.get(str(minutes))
        if o is None or getattr(o, "status", None) != "OK":
            return None
        return _f(getattr(o, "return_pct", None))

    comps = {
        "return_5m": _cmp(_f(row.return_5m_pct), _win_ret(5)),
        "return_15m": _cmp(_f(row.return_15m_pct), _win_ret(15)),
        "return_30m": _cmp(_f(row.return_30m_pct), _win_ret(30)),
        "return_60m": _cmp(_f(row.return_60m_pct), _win_ret(60)),
        "mfe_pct": _cmp(_f(row.mfe_pct), _f(mfe)),
        "mae_pct": _cmp(_f(row.mae_pct), _f(mae)),
        "tp_hit": _bool_cmp(
            None if row.tp_hit is None else bool(row.tp_hit),
            tp_hit_v,
        ),
        "sl_hit": _bool_cmp(
            None if row.sl_hit is None else bool(row.sl_hit),
            sl_hit_v,
        ),
    }
    any_math = any(v == "CHANGED" for v in comps.values())
    low_raw = float(pq_d.get("coverage_ratio_raw") or 0) < 0.8

    # low-coverage reclass
    absent_n = int(pq_d.get("source_absent_confirmed") or 0)
    miss_src = int(pq_d.get("db_missing_source_present") or 0)
    unresolved = int(pq_d.get("unresolved_missing") or 0)
    unavailable = bool(pq_d.get("source_unavailable"))
    if unavailable:
        low_class = "C_UNAVAILABLE"
    elif miss_src > 0:
        low_class = "B_DB_PERSISTENCE_MISSING"
    elif absent_n > 0 and unresolved == 0:
        low_class = "A_SOURCE_ABSENT"
    elif unresolved > 0:
        low_class = "D_UNRESOLVED"
    else:
        low_class = "E_OTHER"

    return {
        "shadow_id": int(row.shadow_id),
        "symbol": str(row.symbol),
        "detected_at": detected.isoformat(),
        "evaluated_60m_at": as_utc(row.evaluated_60m_at).isoformat()
        if row.evaluated_60m_at
        else None,
        "reconstructable": True,
        "path_quality": pq_d,
        "path_pass": path_completeness_pass(pq_d),
        "source_reconcile": evidence.to_detail_dict(),
        "compare": comps,
        "any_math_changed": any_math,
        "low_raw": low_raw,
        "low_class": low_class if low_raw else None,
        "old": {
            "return_60m": _f(row.return_60m_pct),
            "mfe": _f(row.mfe_pct),
            "mae": _f(row.mae_pct),
            "tp_hit": row.tp_hit,
            "sl_hit": row.sl_hit,
        },
        "reconstructed": {
            "return_60m": _win_ret(60),
            "mfe": _f(mfe),
            "mae": _f(mae),
            "tp_hit": tp_hit_v,
            "sl_hit": sl_hit_v,
        },
        "target_60": getattr(windows.get("60"), "status", None),
    }


async def main() -> None:
    factory = get_session_factory()
    with factory() as session:
        rows = list(
            session.scalars(
                select(UpbitOpportunityShadowEntity).where(
                    UpbitOpportunityShadowEntity.deleted_at.is_(None)
                )
            )
        )

        groups = {
            "PRE_COV_COMPLETED": [],
            "POST_COV_V2_COMPLETED": [],
            "ACTIVE": [],
            "TARGET_BLOCKED": [],
            "INVALID": [],
        }
        for r in rows:
            detail = r.evaluation_detail or {}
            pq = detail.get("path_quality") if isinstance(detail, dict) else None
            ver = (pq or {}).get("path_quality_version") if isinstance(pq, dict) else None
            if r.status == SHADOW_STATUS_ACTIVE:
                w60 = ((detail.get("windows") or {}).get("60") or {}).get("status")
                if w60 == "MISSING_CANDLE":
                    groups["TARGET_BLOCKED"].append(int(r.shadow_id))
                else:
                    groups["ACTIVE"].append(int(r.shadow_id))
                continue
            if r.status != SHADOW_STATUS_COMPLETED:
                groups["INVALID"].append(int(r.shadow_id))
                continue
            if ver == PATH_QUALITY_VERSION or ver == "technical_path_quality_v2":
                groups["POST_COV_V2_COMPLETED"].append(int(r.shadow_id))
            else:
                groups["PRE_COV_COMPLETED"].append(int(r.shadow_id))

        pre_ids = set(groups["PRE_COV_COMPLETED"])
        pre_rows = [r for r in rows if int(r.shadow_id) in pre_ids]
        pre_rows.sort(key=lambda x: int(x.shadow_id))

        results: list[dict[str, Any]] = []
        for i, row in enumerate(pre_rows):
            print(f"dry {i+1}/{len(pre_rows)} shadow_id={row.shadow_id}", flush=True)
            try:
                results.append(await _process_row(session, row))
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "shadow_id": int(row.shadow_id),
                        "symbol": str(row.symbol),
                        "reconstructable": False,
                        "reason": type(exc).__name__,
                        "message": str(exc)[:200],
                    }
                )
            # gentle pacing for Upbit range GET
            await asyncio.sleep(0.35)

        # ensure no accidental dirty session
        session.rollback()

    recon = [r for r in results if r.get("reconstructable")]
    not_recon = [r for r in results if not r.get("reconstructable")]
    path_pass = [r for r in recon if r.get("path_pass")]
    unresolved = [
        r
        for r in recon
        if int((r.get("path_quality") or {}).get("unresolved_missing") or 0) > 0
    ]
    unavailable = [
        r
        for r in recon
        if bool((r.get("path_quality") or {}).get("source_unavailable"))
    ]

    def _count_changed(field: str) -> int:
        return sum(1 for r in recon if (r.get("compare") or {}).get(field) == "CHANGED")

    return_changed = sum(
        1
        for r in recon
        if any(
            (r.get("compare") or {}).get(k) == "CHANGED"
            for k in ("return_5m", "return_15m", "return_30m", "return_60m")
        )
    )
    any_math = sum(1 for r in recon if r.get("any_math_changed"))
    low_rows = [r for r in recon if r.get("low_raw")]
    low_class_counts: dict[str, int] = {}
    for r in low_rows:
        c = str(r.get("low_class") or "E_OTHER")
        low_class_counts[c] = low_class_counts.get(c, 0) + 1

    raw_before = [
        float((r.get("path_quality") or {}).get("coverage_ratio_raw") or 0) for r in recon
    ]
    resolved_after = [
        float((r.get("path_quality") or {}).get("coverage_ratio_resolved") or 0)
        for r in recon
    ]
    absent_total = sum(
        int((r.get("path_quality") or {}).get("source_absent_confirmed") or 0)
        for r in recon
    )
    miss_src_total = sum(
        int((r.get("path_quality") or {}).get("db_missing_source_present") or 0)
        for r in recon
    )

    def _dist(vals: list[float]) -> dict[str, Any]:
        if not vals:
            return {"n": 0}
        s = sorted(vals)
        return {
            "n": len(s),
            "min": round(s[0], 4),
            "median": round(s[len(s) // 2], 4),
            "mean": round(sum(s) / len(s), 4),
            "max": round(s[-1], 4),
            "lt_0_8": sum(1 for v in s if v < 0.8),
        }

    changed_rate = (any_math / len(recon)) if recon else None
    may_affect_tp = bool(any_math > 0 or low_class_counts.get("B_DB_PERSISTENCE_MISSING", 0) > 0)

    if not recon:
        apply_verdict = "HISTORICAL_DATA_UNRECOVERABLE"
    elif any_math == 0 and miss_src_total == 0:
        apply_verdict = "COMPARE_ONLY_SUFFICIENT"
    elif miss_src_total > 0 and any_math > 0:
        apply_verdict = "HISTORICAL_APPLY_CANDIDATE"
    elif any_math > 0:
        apply_verdict = "HISTORICAL_APPLY_CANDIDATE"
    else:
        apply_verdict = "COMPARE_ONLY_SUFFICIENT"

    summary = {
        "step": "COV-D0",
        "mode": "READ_ONLY_PRECHECK",
        "path_quality_version": PATH_QUALITY_VERSION,
        "groups": {k: {"count": len(v), "ids": v} for k, v in groups.items()},
        "historical_remediation_candidates": len(groups["PRE_COV_COMPLETED"]),
        "TOTAL_HISTORICAL": len(groups["PRE_COV_COMPLETED"]),
        "RECONSTRUCTABLE": len(recon),
        "NOT_RECONSTRUCTABLE": len(not_recon),
        "PATH_QUALITY_PASS": len(path_pass),
        "PATH_QUALITY_UNRESOLVED": len(unresolved),
        "SOURCE_UNAVAILABLE": len(unavailable),
        "RETURN_CHANGED": return_changed,
        "MFE_CHANGED": _count_changed("mfe_pct"),
        "MAE_CHANGED": _count_changed("mae_pct"),
        "TP_CHANGED": _count_changed("tp_hit"),
        "SL_CHANGED": _count_changed("sl_hit"),
        "ANY_MATH_CHANGED": any_math,
        "changed_rate": round(changed_rate, 4) if changed_rate is not None else None,
        "raw_coverage_dist": _dist(raw_before),
        "resolved_coverage_dist": _dist(resolved_after),
        "source_absent_confirmed_minutes_sum": absent_total,
        "db_missing_source_present_minutes_sum": miss_src_total,
        "low_raw_n": len(low_rows),
        "low_raw_reclass": low_class_counts,
        "COVERAGE_REMEDIATION_MAY_AFFECT_TP_ANALYSIS": may_affect_tp,
        "CURRENT_TP": TP_PCT,
        "CURRENT_SL": SL_PCT,
        "TP_ANALYSIS": "FROZEN_PENDING_COVERAGE_REMEDIATION",
        "OOS": "NOT_STARTED",
        "Historical_APPLY_verdict": apply_verdict,
        "SCHEMA_CHANGE_REQUIRED": False,
        "historical_db_mutation": 0,
        "note": "Math recompute uses DB bars only (no synthetic). Source GET for absence classification; persist_upsert=False.",
    }

    payload = {"summary": summary, "rows": results, "not_reconstructable": not_recon}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = f"""# TECHNICAL COV-D0 — HISTORICAL BACKFILL AND COMPARE PRECHECK

**MODE:** READ-ONLY · **NO APPLY** · **NO DB MUTATION**  
**Date:** 2026-08-15  
**Verdict:** **{apply_verdict}**

## Groups

| Group | Count |
|-------|------:|
| PRE_COV_COMPLETED | {len(groups['PRE_COV_COMPLETED'])} |
| POST_COV_V2_COMPLETED | {len(groups['POST_COV_V2_COMPLETED'])} |
| ACTIVE | {len(groups['ACTIVE'])} |
| TARGET_BLOCKED | {len(groups['TARGET_BLOCKED'])} |
| INVALID | {len(groups['INVALID'])} |

## Preview

| Metric | Value |
|--------|------:|
| RECONSTRUCTABLE | {len(recon)} |
| NOT_RECONSTRUCTABLE | {len(not_recon)} |
| PATH_QUALITY_PASS | {len(path_pass)} |
| UNRESOLVED | {len(unresolved)} |
| SOURCE_UNAVAILABLE | {len(unavailable)} |
| ANY_MATH_CHANGED | {any_math} |
| changed_rate | {summary['changed_rate']} |
| low_raw_n | {len(low_rows)} |
| low_reclass | `{low_class_counts}` |
| absent_minutes_sum | {absent_total} |
| db_missing_source_present_sum | {miss_src_total} |

## APPLY

- Historical APPLY 판정: **{apply_verdict}**
- SCHEMA_CHANGE_REQUIRED: **NO**
- COVERAGE_REMEDIATION_MAY_AFFECT_TP_ANALYSIS: **{may_affect_tp}**
- TP remains FROZEN · OOS NOT_STARTED

## Artifact

JSON: [TECHNICAL_COV_D0_HISTORICAL_COMPARE_PRECHECK.json](TECHNICAL_COV_D0_HISTORICAL_COMPARE_PRECHECK.json)
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("WROTE", OUT)


if __name__ == "__main__":
    asyncio.run(main())
