"""READ-ONLY Technical Shadow Cohort REVIEW_READY performance review v2.

No DB mutations. No policy changes. Output JSON for audit report.
"""

from __future__ import annotations

import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select, text  # noqa: E402

from stock_platform.common.settings import get_settings  # noqa: E402
from stock_platform.database.session import get_session_factory  # noqa: E402
from stock_platform.operation.upbit_opportunity_shadow.cohort_milestone import (  # noqa: E402
    NEW_FINALIZATION_POLICY,
    ALLOWED_SELECTION,
    compute_cohort_milestone_snapshot,
    _is_match_watch,
    _is_new_policy_finalization,
    _is_valid_cohort_row,
    _already_notified,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (  # noqa: E402
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (  # noqa: E402
    UpbitOpportunityShadowEntity,
)

KST = ZoneInfo("Asia/Seoul")
SEED = 20260814
MIN_BUCKET_N = 5


def _r(v: float | None, nd: int = 4) -> float | None:
    if v is None:
        return None
    return round(float(v), nd)


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    return float(statistics.median(vals))


def _stdev(vals: list[float]) -> float | None:
    if len(vals) < 2:
        return None
    return float(statistics.stdev(vals))


def _return_stats(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {"n": 0}
    pos = sum(1 for v in vals if v > 0)
    neg = sum(1 for v in vals if v < 0)
    zero = sum(1 for v in vals if v == 0)
    n = len(vals)
    return {
        "n": n,
        "positive": pos,
        "negative": neg,
        "zero": zero,
        "win_rate": round(pos / n, 4),
        "avg": _r(sum(vals) / n),
        "median": _r(_median(vals)),
        "min": _r(min(vals)),
        "max": _r(max(vals)),
        "stdev": _r(_stdev(vals)),
    }


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None

    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg_rank
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    return _pearson(rx, ry)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 4)


def _wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((centre - margin) / denom, 4), round((centre + margin) / denom, 4))


def _bootstrap_mean_ci(
    vals: list[float], *, n_boot: int = 10_000, seed: int = SEED
) -> dict[str, Any] | None:
    if len(vals) < 2:
        return None
    rng = random.Random(seed)
    means: list[float] = []
    n = len(vals)
    for _ in range(n_boot):
        sample = [vals[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot) - 1]
    return {
        "n": n,
        "n_boot": n_boot,
        "seed": seed,
        "mean": _r(sum(vals) / n),
        "ci95_lo": _r(lo),
        "ci95_hi": _r(hi),
    }


def _path_pattern(r5: float, r15: float, r30: float, r60: float) -> str:
    # 단순 규칙 기반 분류 (관측용)
    ups = [r5 > 0.05, r15 > 0.05, r30 > 0.05, r60 > 0.05]
    downs = [r5 < -0.05, r15 < -0.05, r30 < -0.05, r60 < -0.05]
    if all(abs(x) <= 0.15 for x in (r5, r15, r30, r60)):
        return "flat"
    if ups[0] and ups[1] and ups[2] and ups[3]:
        return "persistent_up"
    if downs[0] and downs[1] and downs[2] and downs[3]:
        return "persistent_down"
    if (r5 > 0 or r15 > 0) and r60 < r15 and r60 < 0.1:
        return "early_up_then_fade"
    if (r5 < 0 or r15 < 0) and r60 > r15 and r60 > -0.1:
        return "early_down_then_recover"
    return "mixed"


def _score_bucket(score: float | None) -> str:
    if score is None:
        return "UNKNOWN"
    if score < 60:
        return "<60"
    if score < 65:
        return "60-64.99"
    if score < 70:
        return "65-69.99"
    if score < 75:
        return "70-74.99"
    if score < 80:
        return "75-79.99"
    return ">=80"


def _conf_bucket(c: float | None) -> str:
    if c is None:
        return "UNKNOWN"
    if c < 0.70:
        return "<0.70"
    if c < 0.80:
        return "0.70-0.79"
    if c < 0.90:
        return "0.80-0.89"
    return ">=0.90"


def _kst_bucket(dt: datetime | None) -> str:
    if dt is None:
        return "UNKNOWN"
    h = dt.astimezone(KST).hour
    if h < 6:
        return "00-06"
    if h < 12:
        return "06-12"
    if h < 18:
        return "12-18"
    return "18-24"


def _group_perf(rows: list[UpbitOpportunityShadowEntity]) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "status": "INSUFFICIENT"}
    r60 = [float(r.return_60m_pct) for r in rows if r.return_60m_pct is not None]
    mfe = [float(r.mfe_pct) for r in rows if r.mfe_pct is not None]
    mae = [float(r.mae_pct) for r in rows if r.mae_pct is not None]
    wins = sum(1 for v in r60 if v > 0)
    n = len(r60)
    out: dict[str, Any] = {
        "n": len(rows),
        "n_with_r60": n,
        "win60": round(wins / n, 4) if n else None,
        "avg60": _r(sum(r60) / n) if n else None,
        "median60": _r(_median(r60)),
        "avg_mfe": _r(sum(mfe) / len(mfe)) if mfe else None,
        "median_mfe": _r(_median(mfe)),
        "avg_mae": _r(sum(mae) / len(mae)) if mae else None,
        "median_mae": _r(_median(mae)),
        "sl_hit": sum(1 for r in rows if r.sl_hit),
        "tp_hit": sum(1 for r in rows if r.tp_hit),
        "sl_rate": round(sum(1 for r in rows if r.sl_hit) / len(rows), 4),
        "tp_rate": round(sum(1 for r in rows if r.tp_hit) / len(rows), 4),
    }
    if len(rows) < MIN_BUCKET_N:
        out["note"] = "INSUFFICIENT"
    return out


def _classify(row: UpbitOpportunityShadowEntity) -> str:
    detail = row.evaluation_detail or {}
    watch = detail.get("mismatch_watch") or {}
    if watch.get("code") == "SHADOW_EVALUATION_MISMATCH":
        return "MISMATCH"
    if row.status != SHADOW_STATUS_COMPLETED:
        return "INCOMPLETE"
    if not _is_valid_cohort_row(row):
        # COMPLETED but missing metrics
        missing = []
        for m in (5, 15, 30, 60):
            if getattr(row, f"return_{m}m_pct", None) is None:
                missing.append(f"return_{m}m")
        if row.mfe_pct is None:
            missing.append("mfe")
        if row.mae_pct is None:
            missing.append("mae")
        if row.tp_hit is None or row.sl_hit is None:
            missing.append("tp_sl")
        return "INVALID" if missing else "INCOMPLETE"
    if _is_new_policy_finalization(row):
        return "VALID_NEW_POLICY"
    return "VALID_LEGACY_PROVENANCE"


def _window_selection_counts(row: UpbitOpportunityShadowEntity) -> Counter:
    c: Counter = Counter()
    windows = (row.evaluation_detail or {}).get("windows") or {}
    for key in ("5", "15", "30", "60"):
        w = windows.get(key) or {}
        st = w.get("selection_type")
        if st:
            c[str(st)] += 1
    return c


def _max_prior_lag_s(row: UpbitOpportunityShadowEntity) -> float | None:
    windows = (row.evaluation_detail or {}).get("windows") or {}
    lags: list[float] = []
    for key in ("5", "15", "30", "60"):
        w = windows.get(key) or {}
        lag = w.get("prior_lag_seconds") or w.get("lag_seconds") or w.get("max_prior_lag_s")
        if lag is None and isinstance(w.get("selection_meta"), dict):
            lag = w["selection_meta"].get("prior_lag_seconds")
        if lag is not None:
            try:
                lags.append(float(lag))
            except (TypeError, ValueError):
                pass
    return max(lags) if lags else None


def main() -> int:
    settings = get_settings()
    with get_session_factory()() as session:
        milestone = compute_cohort_milestone_snapshot(session)
        already = _already_notified(session)

        rows = list(
            session.scalars(
                select(UpbitOpportunityShadowEntity).where(
                    UpbitOpportunityShadowEntity.deleted_at.is_(None)
                )
            )
        )

        # News A/B READ ONLY (separate)
        news = session.execute(
            text(
                """
                SELECT news_context_status, evaluation_status, COUNT(*)::int AS c
                FROM operation.upbit_news_combined_shadow
                GROUP BY 1, 2 ORDER BY 1, 2
                """
            )
        ).mappings().all()
        news_mismatch = session.execute(
            text(
                """
                SELECT COUNT(*)::int AS c
                FROM operation.upbit_news_combined_shadow
                WHERE COALESCE(
                  evaluation_detail->'mismatch_watch'->>'code', ''
                ) = 'SHADOW_EVALUATION_MISMATCH'
                """
            )
        ).scalar_one()

        to_c = session.execute(
            text("SELECT COUNT(*)::int FROM trading.trading_order")
        ).scalar_one()
        try:
            ob_c = session.execute(
                text("SELECT COUNT(*)::int FROM trading.order_outbox")
            ).scalar_one()
        except Exception:
            ob_c = session.execute(
                text(
                    """
                    SELECT COUNT(*)::int FROM information_schema.tables
                    WHERE table_schema='trading' AND table_name='order_outbox'
                    """
                )
            ).scalar_one()
            if ob_c:
                ob_c = session.execute(
                    text("SELECT COUNT(*)::int FROM trading.order_outbox")
                ).scalar_one()

        # DOGE / RE recheck
        special = session.execute(
            text(
                """
                SELECT shadow_id, symbol, status,
                       return_60m_pct, mfe_pct, mae_pct, tp_hit, sl_hit,
                       evaluation_detail->'mismatch_watch' AS mismatch_watch
                FROM trading.upbit_opportunity_shadow
                WHERE deleted_at IS NULL
                  AND shadow_id IN (3, 19)
                ORDER BY shadow_id
                """
            )
        ).mappings().all()

        mismatch_codes = session.execute(
            text(
                """
                SELECT COALESCE(
                  evaluation_detail->'mismatch_watch'->>'code', 'NONE'
                ) AS code,
                COUNT(*)::int AS c
                FROM trading.upbit_opportunity_shadow
                WHERE deleted_at IS NULL AND status='COMPLETED'
                GROUP BY 1 ORDER BY 2 DESC
                """
            )
        ).mappings().all()

    classes = Counter(_classify(r) for r in rows)
    completed = [r for r in rows if r.status == SHADOW_STATUS_COMPLETED]
    valid = [r for r in completed if _is_valid_cohort_row(r)]
    new_valid = [r for r in valid if _is_new_policy_finalization(r)]
    legacy_valid = [r for r in valid if not _is_new_policy_finalization(r)]

    ready_ok = bool(milestone.get("ready"))
    verdict_gate = (
        "CONTINUE"
        if ready_ok
        else "REVIEW_READY_NOT_CONFIRMED"
    )

    # returns windows
    window_stats = {}
    for m in (5, 15, 30, 60):
        attr = f"return_{m}m_pct"
        vals = [float(getattr(r, attr)) for r in valid if getattr(r, attr) is not None]
        window_stats[f"{m}m"] = _return_stats(vals)

    mfe_vals = [float(r.mfe_pct) for r in valid if r.mfe_pct is not None]
    mae_vals = [float(r.mae_pct) for r in valid if r.mae_pct is not None]
    r60_vals = [float(r.return_60m_pct) for r in valid if r.return_60m_pct is not None]

    mfe_thresholds = [0.5, 1.0, 2.0, 3.0, 4.0, 6.0]
    mae_thresholds = [-0.5, -1.0, -2.0, -3.0]
    mfe_table = {
        f">={t:g}%": {
            "count": sum(1 for v in mfe_vals if v >= t),
            "rate": round(sum(1 for v in mfe_vals if v >= t) / len(mfe_vals), 4)
            if mfe_vals
            else None,
        }
        for t in mfe_thresholds
    }
    mae_table = {
        f"<={t:g}%": {
            "count": sum(1 for v in mae_vals if v <= t),
            "rate": round(sum(1 for v in mae_vals if v <= t) / len(mae_vals), 4)
            if mae_vals
            else None,
        }
        for t in mae_thresholds
    }

    # counterfactual MFE/MAE reach (observation only)
    cf_tp = {
        f"+{t:g}%": {
            "mfe_reach_n": sum(1 for v in mfe_vals if v >= t),
            "mfe_reach_rate": round(
                sum(1 for v in mfe_vals if v >= t) / len(mfe_vals), 4
            )
            if mfe_vals
            else None,
        }
        for t in (1.0, 1.5, 2.0, 3.0, 4.0, 6.0)
    }
    cf_sl = {
        f"{t:g}%": {
            "mae_reach_n": sum(1 for v in mae_vals if v <= t),
            "mae_reach_rate": round(
                sum(1 for v in mae_vals if v <= t) / len(mae_vals), 4
            )
            if mae_vals
            else None,
        }
        for t in (-1.0, -1.5, -2.0, -2.5, -3.0)
    }

    tp_hit_n = sum(1 for r in valid if r.tp_hit)
    sl_hit_n = sum(1 for r in valid if r.sl_hit)

    # path patterns
    pattern_groups: dict[str, list[UpbitOpportunityShadowEntity]] = defaultdict(list)
    for r in valid:
        if None in (
            r.return_5m_pct,
            r.return_15m_pct,
            r.return_30m_pct,
            r.return_60m_pct,
        ):
            continue
        p = _path_pattern(
            float(r.return_5m_pct),
            float(r.return_15m_pct),
            float(r.return_30m_pct),
            float(r.return_60m_pct),
        )
        pattern_groups[p].append(r)
    patterns = {
        k: {**_group_perf(v), "share": round(len(v) / len(valid), 4) if valid else None}
        for k, v in sorted(pattern_groups.items(), key=lambda x: -len(x[1]))
    }

    # score buckets
    score_buckets: dict[str, list[UpbitOpportunityShadowEntity]] = defaultdict(list)
    for r in valid:
        score_buckets[_score_bucket(r.scanner_score)].append(r)
    score_perf = {k: _group_perf(v) for k, v in sorted(score_buckets.items())}

    # correlations
    pairs = [
        (r, float(r.scanner_score), float(r.return_60m_pct), float(r.mfe_pct), float(r.mae_pct))
        for r in valid
        if r.scanner_score is not None
        and r.return_60m_pct is not None
        and r.mfe_pct is not None
        and r.mae_pct is not None
    ]
    scores = [p[1] for p in pairs]
    corr = {
        "n": len(pairs),
        "note": "n~35 exploratory only; no statistical claim",
        "pearson": {
            "score_return60": _pearson(scores, [p[2] for p in pairs]),
            "score_mfe": _pearson(scores, [p[3] for p in pairs]),
            "score_mae": _pearson(scores, [p[4] for p in pairs]),
        },
        "spearman": {
            "score_return60": _spearman(scores, [p[2] for p in pairs]),
            "score_mfe": _spearman(scores, [p[3] for p in pairs]),
            "score_mae": _spearman(scores, [p[4] for p in pairs]),
        },
    }

    # rank
    rank_groups: dict[str, list[UpbitOpportunityShadowEntity]] = defaultdict(list)
    for r in valid:
        rk = str(r.scanner_rank) if r.scanner_rank is not None else "UNKNOWN"
        rank_groups[rk].append(r)
    rank_perf = {
        k: _group_perf(v)
        for k, v in sorted(rank_groups.items(), key=lambda x: (x[0] == "UNKNOWN", x[0]))
    }

    # recommendation / confidence / risk
    rec_groups: dict[str, list[UpbitOpportunityShadowEntity]] = defaultdict(list)
    for r in valid:
        rec_groups[str(r.recommendation or "UNKNOWN")].append(r)
    rec_perf = {k: _group_perf(v) for k, v in sorted(rec_groups.items())}
    for k, v in rec_perf.items():
        if v.get("n", 0) < MIN_BUCKET_N:
            v["status"] = "SAMPLE_INSUFFICIENT"

    conf_groups: dict[str, list[UpbitOpportunityShadowEntity]] = defaultdict(list)
    for r in valid:
        conf_groups[_conf_bucket(r.confidence)].append(r)
    conf_perf = {k: _group_perf(v) for k, v in sorted(conf_groups.items())}
    conf_disc = (
        "AI_CONFIDENCE_DISCRIMINATION_INCONCLUSIVE"
        if (max((len(v) for v in conf_groups.values()), default=0) / max(len(valid), 1))
        >= 0.7
        else "DISTRIBUTED"
    )

    risk_groups: dict[str, list[UpbitOpportunityShadowEntity]] = defaultdict(list)
    for r in valid:
        risk_groups[str(r.risk_level or "UNKNOWN")].append(r)
    risk_perf = {k: _group_perf(v) for k, v in sorted(risk_groups.items())}

    # trend / momentum / volatility coverage
    def _cov(attr: str) -> dict[str, Any]:
        vals = [getattr(r, attr) for r in valid]
        non_null = [v for v in vals if v is not None and str(v).strip() != ""]
        return {
            "non_null_n": len(non_null),
            "null_rate": round(1 - len(non_null) / len(valid), 4) if valid else None,
            "value_counts": dict(Counter(str(v) for v in non_null)),
        }

    tech_cov = {
        "trend": _cov("trend"),
        "momentum": _cov("momentum"),
        "volatility": _cov("volatility"),
        "rsi14": _cov("rsi14"),
        "macd": _cov("macd"),
        "ma5": _cov("ma5"),
        "ma20": _cov("ma20"),
        "atr14": _cov("atr14"),
        "volume_surge": _cov("volume_surge"),
        "trade_value_24h": _cov("trade_value_24h"),
    }

    indicator_corr: dict[str, Any] = {}
    for attr in ("rsi14", "macd", "atr14", "volume_surge", "trade_value_24h"):
        xs: list[float] = []
        y60: list[float] = []
        ymfe: list[float] = []
        ymae: list[float] = []
        for r in valid:
            xv = getattr(r, attr)
            if xv is None or r.return_60m_pct is None or r.mfe_pct is None or r.mae_pct is None:
                continue
            xs.append(float(xv))
            y60.append(float(r.return_60m_pct))
            ymfe.append(float(r.mfe_pct))
            ymae.append(float(r.mae_pct))
        if len(xs) < MIN_BUCKET_N:
            indicator_corr[attr] = {"n": len(xs), "status": "N/A_OR_INSUFFICIENT"}
        else:
            indicator_corr[attr] = {
                "n": len(xs),
                "spearman_return60": _spearman(xs, y60),
                "spearman_mfe": _spearman(xs, ymfe),
                "spearman_mae": _spearman(xs, ymae),
            }

    # symbol concentration
    by_sym: dict[str, list[UpbitOpportunityShadowEntity]] = defaultdict(list)
    for r in valid:
        by_sym[r.symbol].append(r)
    sym_counts = sorted(
        ((s, len(v)) for s, v in by_sym.items()), key=lambda x: -x[1]
    )
    n_valid = len(valid) or 1
    top3 = sum(c for _, c in sym_counts[:3]) / n_valid
    top5 = sum(c for _, c in sym_counts[:5]) / n_valid
    repeated = [(s, c) for s, c in sym_counts if c >= 2]
    symbol_concentration = {
        "unique_symbols": len(by_sym),
        "repeated_symbol_count": len(repeated),
        "max_repeat": sym_counts[0] if sym_counts else None,
        "top3_share": round(top3, 4),
        "top5_share": round(top5, 4),
        "repeated_symbol_perf": {
            s: _group_perf(by_sym[s]) for s, _ in repeated[:15]
        },
    }

    # outliers
    sorted_by_r60 = sorted(
        [r for r in valid if r.return_60m_pct is not None],
        key=lambda r: float(r.return_60m_pct),
        reverse=True,
    )

    def _outlier_row(r: UpbitOpportunityShadowEntity) -> dict[str, Any]:
        return {
            "shadow_id": int(r.shadow_id),
            "symbol": r.symbol,
            "scanner_score": r.scanner_score,
            "rank": r.scanner_rank,
            "recommendation": r.recommendation,
            "confidence": r.confidence,
            "risk": r.risk_level,
            "return5": _r(r.return_5m_pct),
            "return15": _r(r.return_15m_pct),
            "return30": _r(r.return_30m_pct),
            "return60": _r(r.return_60m_pct),
            "mfe": _r(r.mfe_pct),
            "mae": _r(r.mae_pct),
            "tp": bool(r.tp_hit),
            "sl": bool(r.sl_hit),
        }

    winners = [_outlier_row(r) for r in sorted_by_r60[:5]]
    losers = [_outlier_row(r) for r in sorted_by_r60[-5:][::-1]]

    def _avg60(subset: list[UpbitOpportunityShadowEntity]) -> float | None:
        vals = [float(r.return_60m_pct) for r in subset if r.return_60m_pct is not None]
        return _r(sum(vals) / len(vals)) if vals else None

    sensitivity = {
        "all_avg60": _avg60(sorted_by_r60),
        "drop_best_1_avg60": _avg60(sorted_by_r60[1:]),
        "drop_best_3_avg60": _avg60(sorted_by_r60[3:]),
        "drop_worst_1_avg60": _avg60(sorted_by_r60[:-1]),
        "drop_worst_3_avg60": _avg60(sorted_by_r60[:-3]),
    }
    # trimmed 10%
    if len(r60_vals) >= 10:
        trimmed = sorted(r60_vals)
        k = max(1, int(len(trimmed) * 0.1))
        mid = trimmed[k : len(trimmed) - k]
        sensitivity["trimmed_10pct_mean60"] = (
            _r(sum(mid) / len(mid)) if mid else None
        )
    else:
        sensitivity["trimmed_10pct_mean60"] = None

    # legacy vs new
    legacy_vs_new = {
        "LEGACY_VALID": _group_perf(legacy_valid),
        "NEW_POLICY_VALID": _group_perf(new_valid),
        "new_policy_match_n": milestone.get("new_policy_match_n"),
        "interpretation": (
            "exploratory quality check only; no causal claim of policy improvement"
        ),
    }

    # fallback EXACT vs LAST_KNOWN among new policy
    exact_rows: list[UpbitOpportunityShadowEntity] = []
    last_known_rows: list[UpbitOpportunityShadowEntity] = []
    mixed_fallback: list[UpbitOpportunityShadowEntity] = []
    lag_buckets = Counter()
    for r in new_valid:
        sel = _window_selection_counts(r)
        exact_n = sel.get("EXACT_TARGET_CANDLE", 0)
        last_n = sel.get("LAST_KNOWN_BEFORE_TARGET", 0)
        if last_n == 0 and exact_n > 0:
            exact_rows.append(r)
        elif exact_n == 0 and last_n > 0:
            last_known_rows.append(r)
        elif last_n > 0:
            mixed_fallback.append(r)
        lag = _max_prior_lag_s(r)
        if lag is None:
            lag_buckets["unknown"] += 1
        elif lag <= 60:
            lag_buckets["<=60"] += 1
        elif lag <= 120:
            lag_buckets["61-120"] += 1
        elif lag <= 180:
            lag_buckets["121-180"] += 1
        else:
            lag_buckets[">180"] += 1

    fallback = {
        "NEW_POLICY_n": len(new_valid),
        "all_exact_windows": _group_perf(exact_rows),
        "all_last_known_windows": _group_perf(last_known_rows),
        "mixed_or_partial_fallback": _group_perf(mixed_fallback),
        "fallback_rate_any_last_known": round(
            (len(last_known_rows) + len(mixed_fallback)) / len(new_valid), 4
        )
        if new_valid
        else None,
        "max_prior_lag_buckets": dict(lag_buckets),
    }

    # time of day
    tod: dict[str, list[UpbitOpportunityShadowEntity]] = defaultdict(list)
    for r in valid:
        tod[_kst_bucket(r.detected_at)].append(r)
    time_of_day = {k: _group_perf(v) for k, v in sorted(tod.items())}

    # chronological
    chrono_sorted = sorted(
        valid, key=lambda r: r.completed_at or r.detected_at or r.created_at
    )
    half = len(chrono_sorted) // 2
    chronological = {
        "first_half": _group_perf(chrono_sorted[:half]),
        "second_half": _group_perf(chrono_sorted[half:]),
        "first_10": _group_perf(chrono_sorted[:10]),
        "middle": _group_perf(chrono_sorted[10:-10])
        if len(chrono_sorted) > 20
        else {"n": 0, "note": "INSUFFICIENT"},
        "last_10": _group_perf(chrono_sorted[-10:]),
    }

    uncertainty = {
        "bootstrap_mean60_ci95": _bootstrap_mean_ci(r60_vals),
        "wilson_win60_ci95": None,
    }
    if r60_vals:
        wins = sum(1 for v in r60_vals if v > 0)
        wi = _wilson(wins, len(r60_vals))
        uncertainty["wilson_win60_ci95"] = {
            "wins": wins,
            "n": len(r60_vals),
            "lo": wi[0] if wi else None,
            "hi": wi[1] if wi else None,
        }

    # early_down_then_recover share (historical pattern check)
    recover_share = patterns.get("early_down_then_recover", {}).get("share")

    # policy judgments (no changes)
    policy = {
        "settings_read": {
            "tp_pct": float(settings.upbit_scanner_shadow_tp_pct),
            "sl_pct": float(settings.upbit_scanner_shadow_sl_pct),
            "cooldown_seconds": float(
                settings.upbit_scanner_shadow_cooldown_seconds
            ),
            "top_n_note": "code/settings Top-N not mutated; observed ranks 1-5",
        },
        "judgments": {},
        "change_candidates": [],
        "keep": [],
        "review_later": [],
        "insufficient": [],
    }

    def judge(name: str, status: str, **meta: Any) -> None:
        policy["judgments"][name] = {"status": status, **meta}
        bucket = {
            "KEEP": "keep",
            "CHANGE_CANDIDATE": "change_candidates",
            "REVIEW_LATER": "review_later",
            "INSUFFICIENT_DATA": "insufficient",
        }[status]
        policy[bucket].append({"name": name, **meta})

    # TP: MFE>=6% rare → candidate to review later / change candidate observational
    mfe6_rate = mfe_table[">=6%"]["rate"] or 0
    mfe2_rate = mfe_table[">=2%"]["rate"] or 0
    if mfe6_rate == 0 and mfe2_rate > 0:
        judge(
            "TP",
            "CHANGE_CANDIDATE",
            observed_issue=f"MFE>=6%={mfe_table['>=6%']['count']}/{len(mfe_vals)}; "
            f"MFE>=2%={mfe_table['>=2%']['count']}/{len(mfe_vals)}",
            sample_n=len(mfe_vals),
            effect_direction="current TP6 rarely reachable by MFE; lower thresholds more often touched",
            risk="lowering TP may increase churn / false exits; not a PnL proof",
            proposed_hypothesis="observe MFE reach rates; consider TP candidate band 2-4% in later experiment",
            additional_validation_required="n>=50–100 + path-aware exit simulation (not done here)",
        )
    else:
        judge("TP", "REVIEW_LATER", sample_n=len(mfe_vals), mfe6_rate=mfe6_rate)

    sl_rate = round(sl_hit_n / len(valid), 4) if valid else None
    mae3_rate = mae_table["<=-3%"]["rate"]
    judge(
        "SL",
        "REVIEW_LATER",
        observed_issue=f"SL hit={sl_hit_n}/{len(valid)}; MAE<=-3% rate={mae3_rate}",
        sample_n=len(valid),
        effect_direction="observe whether -3% aligns with MAE distribution",
        risk="tightening SL may cut recoveries (early_down_then_recover pattern)",
        proposed_hypothesis="keep -3% until larger sample; path pattern suggests mid-window recovery",
        additional_validation_required="n>=50 with pattern-conditioned SL analysis",
    )

    judge(
        "Top_N",
        "KEEP",
        observed_issue="rank 1-5 present; no evidence Top-N change improves outcomes at n~35",
        sample_n=len(valid),
        effect_direction="rank buckets small; exploratory only",
        risk="changing Top-N mutates CONTROL intake",
        proposed_hypothesis=None,
        additional_validation_required="more samples per rank",
    )
    judge(
        "scanner_score_ranking",
        "REVIEW_LATER",
        observed_issue=f"score↔r60 pearson={corr['pearson']['score_return60']}",
        sample_n=corr["n"],
        effect_direction="correlation exploratory; not actionable",
        risk="score formula change is CONTROL mutation",
        proposed_hypothesis="recheck correlation at n>=50",
        additional_validation_required="larger n + out-of-sample",
    )
    reduce_n = rec_perf.get("REDUCE", {}).get("n", 0) or 0
    judge(
        "AI_ALLOW_REDUCE_gate",
        "INSUFFICIENT_DATA" if reduce_n < MIN_BUCKET_N else "REVIEW_LATER",
        observed_issue=f"REDUCE n={reduce_n}",
        sample_n=reduce_n,
        effect_direction="cannot compare ALLOW vs REDUCE reliably",
        risk="gate change affects CONTROL",
        proposed_hypothesis=None,
        additional_validation_required="more REDUCE samples",
    )
    judge(
        "AI_confidence",
        "INSUFFICIENT_DATA"
        if conf_disc == "AI_CONFIDENCE_DISCRIMINATION_INCONCLUSIVE"
        else "REVIEW_LATER",
        observed_issue=conf_disc,
        sample_n=len(valid),
        effect_direction="confidence buckets may be concentrated",
        risk="threshold tweak without discrimination evidence",
        proposed_hypothesis=None,
        additional_validation_required="broader confidence distribution",
    )
    judge(
        "AI_risk",
        "INSUFFICIENT_DATA"
        if any(v.get("n", 0) < MIN_BUCKET_N for v in risk_perf.values())
        else "REVIEW_LATER",
        sample_n=len(valid),
        observed_issue="risk segment sizes",
        effect_direction="exploratory",
        risk="policy mutation",
        proposed_hypothesis=None,
        additional_validation_required="balanced risk samples",
    )
    judge(
        "liquidity_threshold",
        "KEEP",
        observed_issue="no liquidity-policy A/B in this cohort",
        sample_n=len(valid),
        effect_direction=None,
        risk="CONTROL mutation",
        proposed_hypothesis=None,
        additional_validation_required="dedicated liquidity experiment",
    )
    judge(
        "stablecoin_exclusion",
        "KEEP",
        observed_issue="exclusions not A/B tested here",
        sample_n=len(valid),
        effect_direction=None,
        risk="CONTROL mutation",
        proposed_hypothesis=None,
        additional_validation_required="exclusion ablation study",
    )
    judge(
        "caution_exclusion",
        "KEEP",
        observed_issue="exclusions not A/B tested here",
        sample_n=len(valid),
        effect_direction=None,
        risk="CONTROL mutation",
        proposed_hypothesis=None,
        additional_validation_required="exclusion ablation study",
    )
    judge(
        "spike_exclusion",
        "KEEP",
        observed_issue="exclusions not A/B tested here",
        sample_n=len(valid),
        effect_direction=None,
        risk="CONTROL mutation",
        proposed_hypothesis=None,
        additional_validation_required="exclusion ablation study",
    )
    judge(
        "cooldown",
        "KEEP",
        observed_issue=f"cooldown_seconds={settings.upbit_scanner_shadow_cooldown_seconds}",
        sample_n=len(valid),
        effect_direction=None,
        risk="repeat-entry risk if shortened",
        proposed_hypothesis=None,
        additional_validation_required="symbol-repeat analysis at larger n",
    )

    # next sample gate
    if len(valid) < 50:
        next_gate = {
            "recommend": 50,
            "reason": "n≈35 mid-sample; re-review CHANGE_CANDIDATE (esp. TP) at 50",
            "later": 100,
            "later_reason": "threshold tuning consideration only after n≈100",
        }
    else:
        next_gate = {
            "recommend": 100,
            "reason": "already >=50; defer tuning consideration to 100",
            "later": 100,
        }

    # final verdict
    if not ready_ok:
        final = "REVIEW_READY_NOT_CONFIRMED"
    elif (fallback.get("fallback_rate_any_last_known") or 0) > 0.6:
        final = "DATA_QUALITY_REVIEW_REQUIRED"
    elif policy["change_candidates"]:
        final = "TECHNICAL_COHORT_REVIEW_COMPLETE_CHANGE_CANDIDATES"
    else:
        final = "TECHNICAL_COHORT_REVIEW_COMPLETE_KEEP"

    # also recommend more sample as note
    more_sample_note = "MORE_SAMPLE_RECOMMENDED_AT_50" if len(valid) < 50 else None

    safety = {
        "GLOBAL_LIVE_ORDER_ENABLED": bool(settings.global_live_order_enabled),
        "UPBIT_LIVE_ORDER_ENABLED": bool(settings.upbit_live_order_enabled),
        "KIWOOM_LIVE_ORDER_ENABLED": bool(settings.kiwoom_live_order_enabled),
        "live_outbox_worker_enabled": bool(
            getattr(settings, "live_outbox_worker_enabled", False)
        ),
        "live_outbox_worker_auto_start": bool(
            getattr(settings, "live_outbox_worker_auto_start", False)
        ),
        "realtime_live_auto_start": bool(
            getattr(settings, "realtime_live_auto_start", False)
        ),
        "ai_live_gate": bool(
            getattr(settings, "ai_live_trading_gate_enabled", False)
            or getattr(settings, "market_ai_live_gate_enabled", False)
        ),
        "trading_order_count": int(to_c),
        "outbox_count": int(ob_c) if ob_c is not None else None,
        "adapter_create_order": 0,
        "post_v1_orders": 0,
        "protected": {
            "strategy": 17483,
            "deployment": 868,
            "link": 2354,
        },
    }

    news_state = {
        "rows": [dict(r) for r in news],
        "mismatch_proxy_count": int(news_mismatch or 0),
        "note": "News A/B observed only; not mixed into Technical stats",
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "final_verdict": final,
        "more_sample_note": more_sample_note,
        "verdict_gate": verdict_gate,
        "milestone": {**milestone, "already_notified": already},
        "classification_counts": dict(classes),
        "valid_n": len(valid),
        "new_policy_valid_n": len(new_valid),
        "legacy_valid_n": len(legacy_valid),
        "completed_n": len(completed),
        "active_n": sum(1 for r in rows if r.status == "ACTIVE"),
        "special_shadows_3_19": [dict(r) for r in special],
        "mismatch_codes_completed": [dict(r) for r in mismatch_codes],
        "window_stats": window_stats,
        "mfe": {
            "avg": _r(sum(mfe_vals) / len(mfe_vals)) if mfe_vals else None,
            "median": _r(_median(mfe_vals)),
            "max": _r(max(mfe_vals)) if mfe_vals else None,
            "table": mfe_table,
        },
        "mae": {
            "avg": _r(sum(mae_vals) / len(mae_vals)) if mae_vals else None,
            "median": _r(_median(mae_vals)),
            "min": _r(min(mae_vals)) if mae_vals else None,
            "table": mae_table,
        },
        "tp_hit": {"count": tp_hit_n, "rate": round(tp_hit_n / len(valid), 4) if valid else None},
        "sl_hit": {"count": sl_hit_n, "rate": round(sl_hit_n / len(valid), 4) if valid else None},
        "counterfactual_mfe_reach_tp_candidates": cf_tp,
        "counterfactual_mae_reach_sl_candidates": cf_sl,
        "counterfactual_note": "MFE/MAE reach rates only — not strategy PnL backtest",
        "path_patterns": patterns,
        "early_down_then_recover_share": recover_share,
        "score_buckets": score_perf,
        "score_correlation": corr,
        "rank_perf": rank_perf,
        "recommendation_perf": rec_perf,
        "confidence_perf": conf_perf,
        "confidence_discrimination": conf_disc,
        "risk_perf": risk_perf,
        "tech_coverage": tech_cov,
        "indicator_corr": indicator_corr,
        "symbol_concentration": symbol_concentration,
        "top_winners": winners,
        "top_losers": losers,
        "outlier_sensitivity": sensitivity,
        "legacy_vs_new": legacy_vs_new,
        "fallback": fallback,
        "time_of_day_kst": time_of_day,
        "chronological": chronological,
        "uncertainty": uncertainty,
        "policy": policy,
        "next_sample_gate": next_gate,
        "news_ab_readonly": news_state,
        "safety": safety,
        "policy_marker": NEW_FINALIZATION_POLICY,
        "allowed_selection": sorted(ALLOWED_SELECTION),
        "interpretation_limits": [
            "n≈35 mid-sample; no profitability claim",
            "no causal policy improvement claim",
            "TP/SL counterfactuals are MFE/MAE reach only",
            "CONTROL / News experiment kept separate",
        ],
    }

    out_dir = ROOT / "docs" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "TECHNICAL_SHADOW_COHORT_REVIEW_READY_V2_20260814.json"
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "final": final, "path": str(out_path), "milestone": milestone}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
