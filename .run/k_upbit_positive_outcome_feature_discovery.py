# -*- coding: utf-8 -*-
"""WRK-018 Positive-outcome feature discovery — RESEARCH ONLY.

Reuses WRK-017 research SQLite. No API refetch. No production writes.
Discovery → Validation → Test chronological isolation.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from stock_platform.operation.upbit_feature_discovery.stats import (
    assign_quintile,
    effect_size,
    period_bucket,
    profit_concentration,
    quintile_edges,
)
from stock_platform.operation.upbit_momentum_validation.research_candle_store import (
    DEFAULT_DB,
    connect,
    global_span,
    load_symbol_bars,
)
from stock_platform.operation.upbit_positive_edge_entry.report_metrics import (
    FEE_RATE,
    NOTIONAL,
    net_pnl_krw,
    net_return_pct,
    summarize_nets,
)
from stock_platform.operation.upbit_positive_edge_entry.walk_forward import (
    chronological_splits,
    confidence_from_n,
)
from stock_platform.operation.upbit_short_term_turnover.metrics import (
    max_drawdown,
    profit_factor,
)

OUT_JSON = Path(".run/k_upbit_positive_outcome_feature_discovery.json")
OUT_MD = Path(".run/k_upbit_positive_outcome_feature_discovery.md")
WORK_ID = "WRK-20260829-018-UPBIT-POSITIVE-OUTCOME-FEATURE-DISCOVERY"
BASE_COMMIT = "a06e391"
SAMPLE_EVERY = 15
HORIZONS = (30, 60, 120)
PRIMARY = 60
SLIP = 2.0
FEE = FEE_RATE


@dataclass
class Row:
    ts: datetime
    symbol: str
    feat: dict[str, float]
    net: dict[int, float]
    mfe: dict[int, float]
    mae: dict[int, float]


def _sma(xs: list[float], end: int, w: int) -> float | None:
    if end + 1 < w:
        return None
    return sum(xs[end - w + 1 : end + 1]) / float(w)


def _ret(closes: list[float], end: int, lb: int) -> float | None:
    j = end - lb
    if j < 0 or closes[j] <= 0:
        return None
    return (closes[end] / closes[j] - 1.0) * 100.0


def _rv(closes: list[float], end: int, w: int) -> float | None:
    if end < w:
        return None
    rets = []
    for j in range(end - w + 1, end + 1):
        if closes[j - 1] <= 0:
            return None
        rets.append(closes[j] / closes[j - 1] - 1.0)
    if len(rets) < 5:
        return None
    mu = sum(rets) / len(rets)
    return math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets)) * 100.0


def build_rows() -> tuple[list[Row], dict[str, Any]]:
    conn = connect(DEFAULT_DB)
    span = global_span(conn)
    symbols = [
        r[0]
        for r in conn.execute(
            "SELECT symbol FROM candle_minute GROUP BY symbol HAVING COUNT(*)>=1000"
        )
    ]
    series: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        bars = load_symbol_bars(conn, sym)
        if len(bars) < 200:
            continue
        closes = [float(b["close_price"]) for b in bars]
        highs = [float(b["high_price"]) for b in bars]
        lows = [float(b["low_price"]) for b in bars]
        vols = [float(b["volume"]) for b in bars]
        tvs = [float(b["trade_value"]) for b in bars]
        ats = [b["candle_at"] for b in bars]
        by_min = {
            a.replace(second=0, microsecond=0): i for i, a in enumerate(ats)
        }
        series[sym] = {
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "vols": vols,
            "tvs": tvs,
            "ats": ats,
            "by_min": by_min,
        }
    conn.close()

    start = datetime.fromisoformat(str(span["min"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(span["max"]).replace("Z", "+00:00"))
    t0 = start.replace(second=0, microsecond=0)
    if t0.minute % SAMPLE_EVERY:
        t0 += timedelta(minutes=SAMPLE_EVERY - (t0.minute % SAMPLE_EVERY))
    times: list[datetime] = []
    t = t0
    while t <= end - timedelta(minutes=max(HORIZONS)):
        times.append(t)
        t += timedelta(minutes=SAMPLE_EVERY)

    btc = series.get("KRW-BTC")
    rows: list[Row] = []

    for ts in times:
        # market context at ts
        rising = total = 0
        mrets = []
        for ser in series.values():
            idx = ser["by_min"].get(ts)
            if idx is None:
                continue
            r15 = _ret(ser["closes"], idx, 15)
            if r15 is None:
                continue
            total += 1
            mrets.append(r15)
            if r15 > 0:
                rising += 1
        breadth = (rising / total) if total else None
        mkt_ret15 = (sum(mrets) / len(mrets)) if mrets else None
        btc_ret60 = None
        btc_ma_bull = None
        if btc:
            bi = btc["by_min"].get(ts)
            if bi is not None:
                btc_ret60 = _ret(btc["closes"], bi, 60)
                ma5 = _sma(btc["closes"], bi, 5)
                ma20 = _sma(btc["closes"], bi, 20)
                if ma5 is not None and ma20 is not None:
                    btc_ma_bull = 1.0 if ma5 > ma20 else 0.0

        for sym, ser in series.items():
            idx = ser["by_min"].get(ts)
            if idx is None or idx < 65:
                continue
            closes = ser["closes"]
            highs = ser["highs"]
            lows = ser["lows"]
            vols = ser["vols"]
            tvs = ser["tvs"]
            # labels need future
            if idx + max(HORIZONS) >= len(closes):
                continue
            entry = closes[idx]
            if entry <= 0:
                continue

            ma5 = _sma(closes, idx, 5)
            ma20 = _sma(closes, idx, 20)
            ma5p = _sma(closes, idx - 5, 5)
            if ma5 is None or ma20 is None or ma20 == 0:
                continue
            avg_vol = _sma(vols, idx - 1, 20)
            surge = (vols[idx] / avg_vol) if avg_vol and avg_vol > 0 else 0.0
            avg_vol5 = _sma(vols, idx - 1, 5)
            vol_accel = (
                (avg_vol5 / avg_vol) if avg_vol and avg_vol5 and avg_vol > 0 else 1.0
            )
            prior_high = max(highs[idx - 20 : idx]) if idx >= 20 else highs[idx]
            prior_low = min(lows[idx - 20 : idx]) if idx >= 20 else lows[idx]
            dist_high = (entry / prior_high - 1.0) * 100.0 if prior_high else 0.0
            dist_low = (entry / prior_low - 1.0) * 100.0 if prior_low else 0.0
            ma_slope = (
                (ma5 / ma5p - 1.0) * 100.0 if ma5p not in (None, 0) else 0.0
            )
            dist_ma20 = (entry / ma20 - 1.0) * 100.0
            rv15 = _rv(closes, idx, 15) or 0.0
            rv60 = _rv(closes, idx, 60) or 0.0
            range_exp = 0.0
            if idx >= 15:
                recent = max(highs[idx - 14 : idx + 1]) - min(
                    lows[idx - 14 : idx + 1]
                )
                older = max(highs[idx - 29 : idx - 14]) - min(
                    lows[idx - 29 : idx - 14]
                ) if idx >= 29 else recent
                range_exp = (recent / older) if older > 0 else 1.0

            feat = {
                "ret_1m": _ret(closes, idx, 1) or 0.0,
                "ret_3m": _ret(closes, idx, 3) or 0.0,
                "ret_5m": _ret(closes, idx, 5) or 0.0,
                "ret_15m": _ret(closes, idx, 15) or 0.0,
                "ret_30m": _ret(closes, idx, 30) or 0.0,
                "ret_60m": _ret(closes, idx, 60) or 0.0,
                "ma_sep_pct": (ma5 - ma20) / ma20 * 100.0,
                "ma_slope_pct": ma_slope,
                "dist_ma20_pct": dist_ma20,
                "ma_bull": 1.0 if ma5 > ma20 else 0.0,
                "volume_surge": surge,
                "vol_accel": vol_accel,
                "rv_15m": rv15,
                "rv_60m": rv60,
                "range_exp": range_exp,
                "dist_high_20_pct": dist_high,
                "dist_low_20_pct": dist_low,
                "log_tv": math.log10(max(tvs[idx], 1.0)),
                "btc_ret_60m": btc_ret60 if btc_ret60 is not None else 0.0,
                "btc_ma_bull": btc_ma_bull if btc_ma_bull is not None else 0.0,
                "breadth": breadth if breadth is not None else 0.5,
                "mkt_ret_15m": mkt_ret15 if mkt_ret15 is not None else 0.0,
                "hour": float(ts.hour),
                "dow": float(ts.weekday()),
            }

            nets: dict[int, float] = {}
            mfe: dict[int, float] = {}
            mae: dict[int, float] = {}
            for h in HORIZONS:
                j = idx + h
                gross = (closes[j] / entry - 1.0) * 100.0
                nets[h] = net_pnl_krw(net_return_pct(gross, slip_bps=SLIP))
                path_h = highs[idx + 1 : j + 1]
                path_l = lows[idx + 1 : j + 1]
                mfe[h] = (
                    (max(path_h) / entry - 1.0) * 100.0 if path_h else 0.0
                )
                mae[h] = (
                    (min(path_l) / entry - 1.0) * 100.0 if path_l else 0.0
                )

            rows.append(
                Row(ts=ts, symbol=sym, feat=feat, net=nets, mfe=mfe, mae=mae)
            )

    meta = {
        "span": span,
        "symbols": sorted(series.keys()),
        "sample_times": len(times),
        "rows": len(rows),
        "db": str(DEFAULT_DB),
        "days": round((end - start).total_seconds() / 86400.0, 2),
    }
    return rows, meta


FEATURE_KEYS = [
    "ret_1m",
    "ret_5m",
    "ret_15m",
    "ret_30m",
    "ret_60m",
    "ma_sep_pct",
    "ma_slope_pct",
    "dist_ma20_pct",
    "volume_surge",
    "vol_accel",
    "rv_15m",
    "rv_60m",
    "range_exp",
    "dist_high_20_pct",
    "dist_low_20_pct",
    "log_tv",
    "btc_ret_60m",
    "breadth",
    "mkt_ret_15m",
    "hour",
]


def discovery_analysis(disc: list[Row]) -> dict[str, Any]:
    nets = [r.net[PRIMARY] for r in disc]
    ordered = sorted(enumerate(nets), key=lambda kv: kv[1])
    n = len(ordered)
    bot10_i = {i for i, _ in ordered[: max(1, n // 10)]}
    top10_i = {i for i, _ in ordered[max(0, n - n // 10) :]}
    bot25_i = {i for i, _ in ordered[: max(1, n // 4)]}
    top25_i = {i for i, _ in ordered[max(0, n - n // 4) :]}

    winners = [disc[i] for i in top10_i]
    losers = [disc[i] for i in bot10_i]

    contrasts = []
    for fk in FEATURE_KEYS:
        wv = [r.feat[fk] for r in winners]
        lv = [r.feat[fk] for r in losers]
        d = effect_size(wv, lv)
        contrasts.append(
            {
                "feature": fk,
                "winner_mean": round(statistics.fmean(wv), 4),
                "loser_mean": round(statistics.fmean(lv), 4),
                "winner_median": round(statistics.median(wv), 4),
                "loser_median": round(statistics.median(lv), 4),
                "effect_size": round(d, 3) if d is not None else None,
                "n_w": len(wv),
                "n_l": len(lv),
            }
        )
    contrasts.sort(
        key=lambda x: abs(x["effect_size"] or 0), reverse=True
    )

    # binning for top features by |effect|
    edge_map = []
    top_feats = [c["feature"] for c in contrasts[:8]]
    for fk in top_feats:
        vals = [r.feat[fk] for r in disc]
        edges = quintile_edges(vals)
        if not edges:
            continue
        for q in range(1, 6):
            subset = [
                r
                for r in disc
                if assign_quintile(r.feat[fk], edges) == q
            ]
            if len(subset) < 20:
                continue
            n60 = [r.net[60] for r in subset]
            n30 = [r.net[30] for r in subset]
            n120 = [r.net[120] for r in subset]
            # stability EARLY/MIDDLE/LATE on discovery only
            t0 = disc[0].ts
            t1 = disc[-1].ts
            span = max((t1 - t0).total_seconds(), 1)
            period_nets: dict[str, list[float]] = defaultdict(list)
            for r in subset:
                frac = (r.ts - t0).total_seconds() / span
                period_nets[period_bucket(frac)].append(r.net[60])
            signs = []
            for p in ("EARLY", "MIDDLE", "LATE"):
                xs = period_nets.get(p) or []
                if xs:
                    signs.append(1 if sum(xs) > 0 else -1)
            stable = len(signs) >= 2 and abs(sum(signs)) >= len(signs) - 0  # all same?
            # require majority same sign
            stability = (
                "STABLE"
                if signs and abs(sum(signs)) == len(signs)
                else ("MIXED" if signs else "UNKNOWN")
            )
            edge_map.append(
                {
                    "feature": fk,
                    "bin": f"Q{q}",
                    "n": len(subset),
                    "net30": round(sum(n30), 1),
                    "net60": round(sum(n60), 1),
                    "net120": round(sum(n120), 1),
                    "avg60": round(statistics.fmean(n60), 2),
                    "win_rate": round(
                        100.0 * sum(1 for x in n60 if x > 0) / len(n60), 1
                    ),
                    "pf": round(profit_factor(n60), 3),
                    "stability": stability,
                }
            )

    # interactions among top 4 features — favorable bins
    interactions = []
    pair_feats = top_feats[:4]
    for i in range(len(pair_feats)):
        for j in range(i + 1, len(pair_feats)):
            fa, fb = pair_feats[i], pair_feats[j]
            ea = quintile_edges([r.feat[fa] for r in disc])
            eb = quintile_edges([r.feat[fb] for r in disc])
            if not ea or not eb:
                continue
            # find best Qx×Qy by avg net60
            best = None
            for qa in range(1, 6):
                for qb in range(1, 6):
                    subset = [
                        r
                        for r in disc
                        if assign_quintile(r.feat[fa], ea) == qa
                        and assign_quintile(r.feat[fb], eb) == qb
                    ]
                    if len(subset) < 30:
                        continue
                    xs = [r.net[60] for r in subset]
                    avg = statistics.fmean(xs)
                    cand = {
                        "a": fa,
                        "b": fb,
                        "bin": f"{fa}=Q{qa} & {fb}=Q{qb}",
                        "n": len(subset),
                        "avg_net60": round(avg, 2),
                        "total_net60": round(sum(xs), 1),
                        "pf": round(profit_factor(xs), 3),
                        "win_rate": round(
                            100 * sum(1 for x in xs if x > 0) / len(xs), 1
                        ),
                    }
                    if best is None or cand["avg_net60"] > best["avg_net60"]:
                        best = cand
            if best and best["avg_net60"] > 0:
                interactions.append(best)
    interactions.sort(key=lambda x: x["avg_net60"], reverse=True)

    # winner/loser characteristic summary
    top_w = contrasts[:5]
    top_l = sorted(
        contrasts, key=lambda x: (x["effect_size"] or 0)
    )[:5]

    # hour effect
    by_hour: dict[int, list[float]] = defaultdict(list)
    for r in disc:
        by_hour[int(r.feat["hour"])].append(r.net[60])
    hour_stats = {
        str(h): {
            "n": len(xs),
            "avg": round(statistics.fmean(xs), 2),
            "net": round(sum(xs), 1),
        }
        for h, xs in sorted(by_hour.items())
        if len(xs) >= 30
    }

    # symbol concentration of top winners
    w_sym = Counter(r.symbol for r in winners)
    symbol_dep = {
        "top_symbols": w_sym.most_common(5),
        "winner_n": len(winners),
    }

    return {
        "contrasts": contrasts[:15],
        "edge_map": edge_map,
        "interactions": interactions[:5],
        "top_winner_features": top_w,
        "top_loser_features": top_l,
        "hour_stats": hour_stats,
        "symbol_dep": symbol_dep,
        "n_discovery": n,
        "top10_n": len(top10_i),
        "bot10_n": len(bot10_i),
    }


def _edges_from_disc(disc: list[Row], fk: str) -> list[float] | None:
    return quintile_edges([r.feat[fk] for r in disc])


def build_hypotheses(disc: list[Row], analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Create up to 5 NEW explainable hypotheses from discovery only.

    Not CURRENT_MA / frozen MOMENTUM renames.
    """

    # Collect favorable bins (positive avg60 + STABLE preferred)
    good_bins = [
        e
        for e in analysis["edge_map"]
        if e["avg60"] > 0 and e["n"] >= 40 and e["pf"] >= 1.0
    ]
    good_bins.sort(key=lambda x: (x["stability"] == "STABLE", x["avg60"]), reverse=True)

    # Precompute edges on discovery for freeze
    edge_cache: dict[str, list[float]] = {}
    for fk in FEATURE_KEYS:
        e = _edges_from_disc(disc, fk)
        if e:
            edge_cache[fk] = e

    hyps: list[dict[str, Any]] = []

    def add(
        name: str,
        rationale: str,
        features: list[str],
        predicate: Callable[[Row], bool],
        horizon: int,
        context: str,
    ) -> None:
        if len(hyps) >= 5:
            return
        hyps.append(
            {
                "name": name,
                "rationale": rationale,
                "features": features,
                "horizon": horizon,
                "market_context": context,
                "predicate": predicate,
            }
        )

    # H from best single bins
    used = set()
    for b in good_bins:
        if len(hyps) >= 3:
            break
        fk = b["feature"]
        q = int(b["bin"][1])
        key = (fk, q)
        if key in used or fk not in edge_cache:
            continue
        used.add(key)
        edges = edge_cache[fk]

        def pred_factory(feature: str, qq: int, ed: list[float]):
            def _p(r: Row) -> bool:
                return assign_quintile(r.feat[feature], ed) == qq

            return _p

        add(
            name=f"BIN_{fk.upper()}_{b['bin']}",
            rationale=f"Discovery: {fk} {b['bin']} avg60={b['avg60']} pf={b['pf']} {b['stability']}",
            features=[fk],
            predicate=pred_factory(fk, q, edges),
            horizon=60,
            context="feature-bin from winner contrast",
        )

    # Interaction-based
    for inter in analysis.get("interactions") or []:
        if len(hyps) >= 5:
            break
        # parse "fa=Q3 & fb=Q5"
        try:
            left, right = inter["bin"].split(" & ")
            fa, qa_s = left.split("=")
            fb, qb_s = right.split("=")
            qa = int(qa_s[1:])
            qb = int(qb_s[1:])
        except Exception:  # noqa: BLE001
            continue
        if fa not in edge_cache or fb not in edge_cache:
            continue
        ea, eb = edge_cache[fa], edge_cache[fb]

        def pred_inter(
            feature_a: str = fa,
            feature_b: str = fb,
            q_a: int = qa,
            q_b: int = qb,
            ed_a: list[float] = ea,
            ed_b: list[float] = eb,
        ):
            def _p(r: Row) -> bool:
                return (
                    assign_quintile(r.feat[feature_a], ed_a) == q_a
                    and assign_quintile(r.feat[feature_b], ed_b) == q_b
                )

            return _p

        add(
            name=f"IX_{fa}_{qa}_{fb}_{qb}",
            rationale=f"Discovery interaction avg60={inter['avg_net60']} n={inter['n']}",
            features=[fa, fb],
            predicate=pred_inter(),
            horizon=60,
            context="2-way interaction",
        )

    # Context-aware constructive rules (still discovery-informed, not MA/momentum clone)
    # Prefer: high breadth + compressed vol + not near high (room to run) + liquidity
    if "breadth" in edge_cache and "rv_15m" in edge_cache and "dist_high_20_pct" in edge_cache:
        eb = edge_cache["breadth"]
        er = edge_cache["rv_15m"]
        eh = edge_cache["dist_high_20_pct"]
        el = edge_cache.get("log_tv")

        def pred_calm_breadth(r: Row) -> bool:
            ok = (
                assign_quintile(r.feat["breadth"], eb) >= 4
                and assign_quintile(r.feat["rv_15m"], er) <= 2
                and assign_quintile(r.feat["dist_high_20_pct"], eh) <= 3
            )
            if el:
                ok = ok and assign_quintile(r.feat["log_tv"], el) >= 3
            return ok

        add(
            name="CALM_BREADTH_LIQUID",
            rationale="High breadth + low short vol + not extended to highs + liquidity",
            features=["breadth", "rv_15m", "dist_high_20_pct", "log_tv"],
            predicate=pred_calm_breadth,
            horizon=60,
            context="market breadth supportive, calm microstructure",
        )

    if "dist_low_20_pct" in edge_cache and "btc_ret_60m" in edge_cache and "vol_accel" in edge_cache:
        elow = edge_cache["dist_low_20_pct"]
        ebtc = edge_cache["btc_ret_60m"]
        eva = edge_cache["vol_accel"]

        def pred_bounce(r: Row) -> bool:
            # near local low (low dist_low quintile means closer to low? dist_low is % above low — Q1 is near low)
            return (
                assign_quintile(r.feat["dist_low_20_pct"], elow) <= 2
                and assign_quintile(r.feat["btc_ret_60m"], ebtc) >= 4
                and assign_quintile(r.feat["vol_accel"], eva) >= 3
                and r.feat["ret_5m"] > 0
            )

        add(
            name="BTC_UP_LOCAL_LOW_VOLUME_WAKE",
            rationale="BTC up + price near 20m low + volume waking + 5m green (not frozen momentum)",
            features=["dist_low_20_pct", "btc_ret_60m", "vol_accel", "ret_5m"],
            predicate=pred_bounce,
            horizon=60,
            context="BTC supportive local reclaim",
        )

    return hyps[:5]


def eval_hyp(
    rows: list[Row],
    hyp: dict[str, Any],
    *,
    days: float,
    slip: float = SLIP,
) -> dict[str, Any]:
    h = int(hyp["horizon"])
    matched = [r for r in rows if hyp["predicate"](r)]
    # recompute net with slip if needed — labels already at 2bps; for sensitivity use gross approx
    # We only stored net at 2bps. For 1/5 bps approximate by adjusting slip delta on gross.
    # Approximate: net_x = net_2bps + notional*((2-x)*2/10000)*100/100 wait
    # net_pnl difference per bps side: NOTIONAL * (bps_delta/10000)*2
    nets = [r.net[h] for r in matched]
    if slip != SLIP:
        delta_bps = slip - SLIP
        adj = NOTIONAL * (delta_bps / 10000.0) * 2.0
        # higher slip → lower net
        nets = [n - adj for n in nets]
    summary = summarize_nets(nets, days=max(days, 1))
    summary["loss_streak"] = _loss_streak(nets)
    summary["profit_concentration"] = profit_concentration(nets)
    # symbol concentration
    if matched:
        by_sym = Counter(r.symbol for r in matched if r.net[h] > 0)
        total_win = sum(r.net[h] for r in matched if r.net[h] > 0)
        top_share = 0.0
        if total_win > 0 and by_sym:
            top_sym, _ = by_sym.most_common(1)[0]
            top_share = sum(
                r.net[h] for r in matched if r.symbol == top_sym and r.net[h] > 0
            ) / total_win
        summary["top_symbol_profit_share"] = round(top_share, 3)
    else:
        summary["top_symbol_profit_share"] = None
    # period stability on this split
    if matched:
        t0, t1 = matched[0].ts, matched[-1].ts
        span = max((t1 - t0).total_seconds(), 1)
        signs = []
        for p_name in ("EARLY", "MIDDLE", "LATE"):
            xs = [
                r.net[h]
                for r in matched
                if period_bucket((r.ts - t0).total_seconds() / span) == p_name
            ]
            if xs:
                signs.append(1 if sum(xs) > 0 else -1)
        summary["period_stability"] = (
            "STABLE"
            if signs and abs(sum(signs)) == len(signs)
            else "MIXED"
        )
    else:
        summary["period_stability"] = "EMPTY"
    summary["zero_trade_days_pct"] = _zero_days(
        [r.ts for r in matched], days
    )
    return summary


def _loss_streak(nets: list[float]) -> int:
    best = cur = 0
    for n in nets:
        if n < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _zero_days(ts: list[datetime], days: float) -> float:
    active = {t.date() for t in ts}
    d = max(int(round(days)), 1)
    return round(100.0 * max(0, d - len(active)) / d, 1)


def main() -> None:
    rows, meta = build_rows()
    rows = sorted(rows, key=lambda r: r.ts)
    days = float(meta["days"])
    disc, val, test = chronological_splits(rows)
    disc_days = max(days * 0.6, 1)
    val_days = max(days * 0.2, 1)
    test_days = max(days * 0.2, 1)

    analysis = discovery_analysis(disc)
    hyps = build_hypotheses(disc, analysis)

    # Freeze predicates: already closures over discovery edges
    val_results = {}
    survivors = []
    for hyp in hyps:
        meta_h = {k: v for k, v in hyp.items() if k != "predicate"}
        vr = eval_hyp(val, hyp, days=val_days)
        val_results[hyp["name"]] = {**meta_h, **vr}
        # promote to test if not clearly negative
        if (vr.get("n") or 0) >= 20 and (vr.get("total_net") or 0) > -500:
            # allow slightly negative val if pf near 1 — still gate harsh losers
            if (vr.get("pf") or 0) >= 0.95 or (vr.get("total_net") or 0) > 0:
                survivors.append(hyp)

    test_results = {}
    for hyp in survivors:
        meta_h = {k: v for k, v in hyp.items() if k != "predicate"}
        tr = eval_hyp(test, hyp, days=test_days)
        slip_sens = {
            f"{bps}bps": eval_hyp(test, hyp, days=test_days, slip=bps)
            for bps in (1.0, 2.0, 5.0)
        }
        test_results[hyp["name"]] = {
            **meta_h,
            **tr,
            "slip_sensitivity": {
                k: {
                    "n": v.get("n"),
                    "pf": v.get("pf"),
                    "total_net": v.get("total_net"),
                }
                for k, v in slip_sens.items()
            },
        }

    # Pick best by TEST
    best = None
    for name, tr in test_results.items():
        conc = tr.get("profit_concentration") or {}
        ok = (
            (tr.get("total_net") or 0) > 0
            and (tr.get("pf") or 0) >= 1.10
            and (tr.get("n") or 0) >= 30
            and float(conc.get("top2") or 0) < 0.55
            and tr.get("period_stability") != "EMPTY"
            and float((tr.get("slip_sensitivity") or {}).get("5.0bps", {}).get("pf") or 0)
            >= 0.85
        )
        tr["promotion_ok"] = ok
        if ok:
            if best is None or float(tr["total_net"]) > float(best["total_net"]):
                best = {"name": name, **tr}

    positive_names = [
        n for n, tr in test_results.items() if tr.get("promotion_ok")
    ]
    multi = {"applied": False}
    if len(positive_names) >= 2:
        # dedupe by ts+symbol — take first matching hyp order
        seen: set[tuple] = set()
        nets = []
        for r in test:
            hit = False
            for hyp in survivors:
                if hyp["name"] not in positive_names:
                    continue
                if hyp["predicate"](r):
                    key = (r.ts.isoformat(), r.symbol)
                    if key in seen:
                        break
                    seen.add(key)
                    nets.append(r.net[int(hyp["horizon"])])
                    hit = True
                    break
        multi = {
            "applied": True,
            "components": positive_names,
            "summary": summarize_nets(nets, days=test_days),
        }

    if best:
        classification = "A_NEW_ENTRY_EDGE_FOUND"
    elif any(
        (tr.get("n") or 0) >= 20
        and ((tr.get("pf") or 0) >= 1.0 or (tr.get("total_net") or 0) > 0)
        for tr in test_results.values()
    ) or any(
        (vr.get("pf") or 0) >= 1.05 and (vr.get("n") or 0) >= 30
        for vr in val_results.values()
    ):
        classification = "B_PROMISING_FEATURES_NEED_MORE_DATA"
    else:
        classification = "C_NO_STABLE_FEATURE_EDGE_FOUND"

    # If no survivors and discovery found nothing stable → C
    if not hyps:
        classification = "C_NO_STABLE_FEATURE_EDGE_FOUND"

    winner_chars = [
        f"{c['feature']}: winners mean {c['winner_mean']} vs losers {c['loser_mean']} (d={c['effect_size']})"
        for c in analysis["top_winner_features"][:5]
    ]
    loser_chars = [
        f"{c['feature']}: losers elevated mean {c['loser_mean']} vs winners {c['winner_mean']} (d={c['effect_size']})"
        for c in analysis["top_loser_features"][:5]
    ]

    remaining = {
        "A_NEW_ENTRY_EDGE_FOUND": "Forward Shadow validate winning hypothesis only — no REAL.",
        "B_PROMISING_FEATURES_NEED_MORE_DATA": "Collect more OOS days; do not retune thresholds on TEST.",
        "C_NO_STABLE_FEATURE_EDGE_FOUND": "Stop candle-only technical micro-tuning; next: order-flow/microstructure or external information.",
    }[classification]

    report = {
        "WORK_ID": WORK_ID,
        "FINAL_VERDICT": "UPBIT_POSITIVE_OUTCOME_FEATURE_DISCOVERY_COMPLETE",
        "CLASSIFICATION": classification,
        "BASE_COMMIT": BASE_COMMIT,
        "RESULT_COMMIT": None,
        "PARENT": "WRK-20260829-017-UPBIT-MOMENTUM-60-90D-EDGE-VALIDATION",
        "DATA": {
            "WINDOW": f"{meta['days']}d",
            "SYMBOLS": meta["symbols"],
            "ROWS": meta["rows"],
            "OPPORTUNITIES": meta["rows"],
            "DISCOVERY_N": len(disc),
            "VALIDATION_N": len(val),
            "TEST_N": len(test),
            "SAMPLE_TIMES": meta["sample_times"],
            "RESEARCH_DB": meta["db"],
            "API_REFETCH": False,
        },
        "TOP_WINNER_CHARACTERISTICS": winner_chars,
        "TOP_LOSER_CHARACTERISTICS": loser_chars,
        "FEATURE_EDGE_MAP": analysis["edge_map"][:40],
        "INTERACTIONS": analysis["interactions"],
        "HOUR_EFFECT": analysis["hour_stats"],
        "SYMBOL_DEP": analysis["symbol_dep"],
        "HYPOTHESES": [
            {k: v for k, v in h.items() if k != "predicate"} for h in hyps
        ],
        "VALIDATION": val_results,
        "TEST": test_results,
        "BEST": best,
        "MULTI": multi,
        "AI": {"status": "SKIPPED", "reason": "no reliable timestamp pairing"},
        "AUTO_ONLY": {"status": "SKIPPED"},
        "EXIT_TUNING": {"status": "SKIPPED"},
        "PRODUCTION": {
            "REAL_POLICY_CHANGED": False,
            "REAL_ORDER_CREATED_BY_RESEARCH": 0,
            "LIVE_ARM_MUTATION": False,
        },
        "REMAINING": remaining,
    }

    # markdown
    lines = [
        "# WRK-018 Positive Outcome Feature Discovery",
        "",
        f"**Classification:** `{classification}`",
        f"**Rows:** {meta['rows']} · Discovery/Val/Test = {len(disc)}/{len(val)}/{len(test)}",
        "",
        "## Winner characteristics",
    ]
    for w in winner_chars:
        lines.append(f"- {w}")
    lines += ["", "## Loser characteristics"]
    for w in loser_chars:
        lines.append(f"- {w}")
    lines += [
        "",
        "## Feature edge map (top)",
        "",
        "| Feature | Bin | N | Net30 | Net60 | Net120 | Win% | PF | Stability |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for e in analysis["edge_map"][:25]:
        lines.append(
            f"| {e['feature']} | {e['bin']} | {e['n']} | {e['net30']} | {e['net60']} | "
            f"{e['net120']} | {e['win_rate']} | {e['pf']} | {e['stability']} |"
        )
    lines += ["", "## Hypotheses"]
    for h in hyps:
        vr = val_results.get(h["name"], {})
        tr = test_results.get(h["name"])
        lines.append(f"### {h['name']}")
        lines.append(f"- Rule features: {h['features']}")
        lines.append(f"- Why: {h['rationale']}")
        lines.append(
            f"- VAL: n={vr.get('n')} pf={vr.get('pf')} net={vr.get('total_net')}"
        )
        if tr:
            lines.append(
                f"- TEST: n={tr.get('n')} pf={tr.get('pf')} net={tr.get('total_net')} "
                f"promo={tr.get('promotion_ok')}"
            )
        else:
            lines.append("- TEST: not promoted from validation")
    lines += [
        "",
        f"## BEST: `{best['name'] if best else None}`",
        "",
        f"**{classification}**",
        "",
        remaining,
        "",
        "`REAL_POLICY_CHANGED=false`",
        "",
        "STOP.",
    ]

    # Strip predicates for JSON
    OUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "classification": classification,
                "rows": meta["rows"],
                "hyps": [h["name"] for h in hyps],
                "survivors": list(test_results.keys()),
                "best": best["name"] if best else None,
                "best_test": (
                    {
                        "pf": best.get("pf"),
                        "net": best.get("total_net"),
                        "n": best.get("n"),
                    }
                    if best
                    else None
                ),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
