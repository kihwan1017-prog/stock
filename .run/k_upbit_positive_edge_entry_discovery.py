# -*- coding: utf-8 -*-
"""WRK-016 Positive-edge entry discovery — SHADOW ONLY consolidated run."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_positive_edge_entry.families import (
    FAMILY_KEYS,
    evaluate_families,
)
from stock_platform.operation.upbit_positive_edge_entry.regime import (
    MarketRegime,
    classify_regime,
)
from stock_platform.operation.upbit_positive_edge_entry.report_metrics import (
    FEE_RATE,
    HORIZONS,
    NOTIONAL,
    SLIP_BPS_DEFAULT,
    net_pnl_krw,
    net_return_pct,
    promotion_ok,
    summarize_nets,
)
from stock_platform.operation.upbit_positive_edge_entry.walk_forward import (
    chronological_splits,
    confidence_from_n,
)

OUT_JSON = Path(".run/k_upbit_positive_edge_entry_discovery.json")
OUT_MD = Path(".run/k_upbit_positive_edge_entry_discovery.md")
WORK_ID = "WRK-20260829-016-UPBIT-POSITIVE-EDGE-ENTRY-DISCOVERY"
BASE_COMMIT = "5fedea2"
SAMPLE_EVERY_MIN = 15
TOP_N_CROSS = 3
MAX_SYMBOLS = 28
PRIMARY_HORIZON = 30  # entry quality primary (minutes)


@dataclass
class Bar:
    at: datetime
    o: float
    h: float
    low: float
    c: float
    v: float
    tv: float


def _sma(xs: list[float], end: int, w: int) -> float | None:
    if end + 1 < w or w <= 0:
        return None
    chunk = xs[end - w + 1 : end + 1]
    return sum(chunk) / w


def _rsi(closes: list[float], end: int, period: int = 14) -> float | None:
    if end < period:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(end - period + 1, end + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100.0 - (100.0 / (1.0 + rs))


def _ret(closes: list[float], end: int, lookback: int) -> float | None:
    j = end - lookback
    if j < 0 or closes[j] <= 0:
        return None
    return (closes[end] / closes[j] - 1.0) * 100.0


def load_top_symbols(session, start: datetime, limit: int) -> list[str]:
    rows = session.execute(
        text(
            """
            SELECT i.symbol
            FROM market.candle_minute c
            JOIN market.instrument i ON i.instrument_id = c.instrument_id
            WHERE i.exchange_code='UPBIT' AND i.symbol LIKE 'KRW-%'
              AND i.symbol <> 'KRW-USDT'
              AND c.timeframe=1 AND c.candle_at >= :start
            GROUP BY i.symbol
            ORDER BY SUM(c.trade_value) DESC NULLS LAST
            LIMIT :lim
            """
        ),
        {"start": start, "lim": limit},
    ).scalars().all()
    return [str(s) for s in rows]


def load_bars(session, symbol: str, start: datetime) -> list[Bar]:
    rows = session.execute(
        text(
            """
            SELECT c.candle_at, c.open_price, c.high_price, c.low_price,
                   c.close_price, c.volume, c.trade_value
            FROM market.candle_minute c
            JOIN market.instrument i ON i.instrument_id = c.instrument_id
            WHERE i.exchange_code='UPBIT' AND i.symbol=:sym
              AND c.timeframe=1 AND c.candle_at >= :start
            ORDER BY c.candle_at
            """
        ),
        {"sym": symbol, "start": start},
    ).mappings().all()
    out: list[Bar] = []
    for r in rows:
        at = r["candle_at"]
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        out.append(
            Bar(
                at=at,
                o=float(r["open_price"]),
                h=float(r["high_price"]),
                low=float(r["low_price"]),
                c=float(r["close_price"]),
                v=float(r["volume"] or 0),
                tv=float(r["trade_value"] or 0),
            )
        )
    return out


def build_symbol_series(bars: list[Bar]) -> dict[str, Any]:
    closes = [b.c for b in bars]
    highs = [b.h for b in bars]
    vols = [b.v for b in bars]
    return {
        "bars": bars,
        "closes": closes,
        "highs": highs,
        "vols": vols,
        "by_min": {b.at.replace(second=0, microsecond=0): i for i, b in enumerate(bars)},
    }


def feature_at(series: dict[str, Any], i: int) -> dict[str, Any] | None:
    bars: list[Bar] = series["bars"]
    closes: list[float] = series["closes"]
    highs: list[float] = series["highs"]
    vols: list[float] = series["vols"]
    if i < 25 or i >= len(bars):
        return None
    ma5 = _sma(closes, i, 5)
    ma20 = _sma(closes, i, 20)
    ma5_prev = _sma(closes, i - 5, 5)
    sep = None
    if ma5 is not None and ma20 is not None and ma20 != 0:
        sep = (ma5 - ma20) / ma20 * 100.0
    avg_vol = _sma(vols, i - 1, 20)  # exclude current for surge base
    surge = (vols[i] / avg_vol) if avg_vol and avg_vol > 0 else 0.0
    # breakout vs prior 20 highs excluding current bar
    prior_high = max(highs[i - 20 : i]) if i >= 20 else None
    breakout = prior_high is not None and closes[i] > prior_high
    ma_slope = None
    if ma5 is not None and ma5_prev is not None and ma5_prev != 0:
        ma_slope = (ma5 / ma5_prev - 1.0) * 100.0
    return {
        "close": closes[i],
        "ma5": ma5,
        "ma20": ma20,
        "ma_sep_pct": sep,
        "ma5_slope_pct": ma_slope,
        "volume_surge": surge,
        "rsi14": _rsi(closes, i, 14),
        "ret_5m_pct": _ret(closes, i, 5),
        "ret_15m_pct": _ret(closes, i, 15),
        "ret_60m_pct": _ret(closes, i, 60),
        "breakout_20m": breakout,
        "trade_value": bars[i].tv,
    }


def forward_labels(series: dict[str, Any], i: int) -> dict[str, float | None]:
    """Labels only — never used as features."""

    closes: list[float] = series["closes"]
    highs: list[float] = series["highs"]
    lows: list[float] = [b.low for b in series["bars"]]
    entry = closes[i]
    if entry <= 0:
        return {f"ret_{h}m": None for h in HORIZONS} | {"mfe": None, "mae": None}
    out: dict[str, float | None] = {}
    max_h = max(HORIZONS)
    end = min(len(closes) - 1, i + max_h)
    path_h = highs[i + 1 : end + 1]
    path_l = lows[i + 1 : end + 1]
    mfe = ((max(path_h) / entry) - 1.0) * 100.0 if path_h else None
    mae = ((min(path_l) / entry) - 1.0) * 100.0 if path_l else None
    out["mfe"] = mfe
    out["mae"] = mae
    for h in HORIZONS:
        j = i + h
        if j >= len(closes):
            out[f"ret_{h}m"] = None
        else:
            out[f"ret_{h}m"] = (closes[j] / entry - 1.0) * 100.0
    return out


def resolve_window(session) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    row = session.execute(
        text(
            """
            SELECT MIN(c.candle_at) AS mn, MAX(c.candle_at) AS mx, COUNT(*) AS n
            FROM market.candle_minute c
            JOIN market.instrument i ON i.instrument_id = c.instrument_id
            WHERE i.exchange_code='UPBIT' AND c.timeframe=1
              AND c.candle_at >= NOW() - INTERVAL '90 days'
            """
        )
    ).mappings().one()
    mn, mx = row["mn"], row["mx"]
    if mn is None or mx is None:
        raise RuntimeError("no candle data")
    if mn.tzinfo is None:
        mn = mn.replace(tzinfo=timezone.utc)
    if mx.tzinfo is None:
        mx = mx.replace(tzinfo=timezone.utc)
    days = max(1.0, (mx - mn).total_seconds() / 86400.0)
    chosen = "90d" if days >= 85 else ("60d" if days >= 55 else ("30d" if days >= 25 else f"{days:.0f}d_available"))
    return {
        "chosen": chosen,
        "start": mn,
        "end": mx,
        "days": round(days, 2),
        "candle_rows_90d_window": int(row["n"] or 0),
        "note": "Canonical store shorter than 90d — use full available span",
    }


def main() -> None:
    session = get_session_factory()()
    try:
        window = resolve_window(session)
        start: datetime = window["start"]
        days = float(window["days"])
        symbols = load_top_symbols(session, start, MAX_SYMBOLS)
        series_by: dict[str, dict[str, Any]] = {}
        for sym in symbols:
            bars = load_bars(session, sym, start - timedelta(hours=2))
            if len(bars) >= 80:
                series_by[sym] = build_symbol_series(bars)

        if "KRW-BTC" not in series_by and symbols:
            # ensure BTC for regime
            btc = load_bars(session, "KRW-BTC", start - timedelta(hours=2))
            if len(btc) >= 80:
                series_by["KRW-BTC"] = build_symbol_series(btc)

        btc = series_by.get("KRW-BTC")
        # vol thresholds from BTC 60m realized vol distribution
        btc_vols: list[float] = []
        if btc:
            closes = btc["closes"]
            for i in range(60, len(closes)):
                rets = [
                    (closes[j] / closes[j - 1] - 1.0)
                    for j in range(i - 59, i + 1)
                    if closes[j - 1] > 0
                ]
                if len(rets) >= 30:
                    mu = sum(rets) / len(rets)
                    var = sum((r - mu) ** 2 for r in rets) / len(rets)
                    btc_vols.append(math.sqrt(var) * 100.0)
        vol_sorted = sorted(btc_vols) if btc_vols else [0.05, 0.1]
        vol_hi = vol_sorted[int(len(vol_sorted) * 0.75)]
        vol_lo = vol_sorted[int(len(vol_sorted) * 0.25)]

        # sample grid
        grid_start = start.replace(second=0, microsecond=0)
        if grid_start.minute % SAMPLE_EVERY_MIN:
            grid_start += timedelta(
                minutes=SAMPLE_EVERY_MIN - (grid_start.minute % SAMPLE_EVERY_MIN)
            )
        sample_times: list[datetime] = []
        t = grid_start
        while t <= window["end"] - timedelta(minutes=max(HORIZONS)):
            sample_times.append(t)
            t += timedelta(minutes=SAMPLE_EVERY_MIN)

        # opportunities
        opps: list[dict[str, Any]] = []
        regime_at: dict[datetime, str] = {}

        for ts in sample_times:
            # breadth + BTC regime
            rising = 0
            total = 0
            for sym, ser in series_by.items():
                idx = ser["by_min"].get(ts)
                if idx is None:
                    # nearest <= ts
                    # skip if missing exact for speed
                    continue
                r15 = _ret(ser["closes"], idx, 15)
                if r15 is None:
                    continue
                total += 1
                if r15 > 0:
                    rising += 1
            breadth = (rising / total) if total else None

            btc_feat = None
            btc_idx = None
            if btc:
                btc_idx = btc["by_min"].get(ts)
                if btc_idx is not None:
                    btc_feat = feature_at(btc, btc_idx)
            rv = None
            if btc and btc_idx is not None and btc_idx >= 60:
                closes = btc["closes"]
                rets = [
                    (closes[j] / closes[j - 1] - 1.0)
                    for j in range(btc_idx - 59, btc_idx + 1)
                    if closes[j - 1] > 0
                ]
                if rets:
                    mu = sum(rets) / len(rets)
                    rv = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets)) * 100.0

            reg = classify_regime(
                btc_ret_60m_pct=(btc_feat or {}).get("ret_60m_pct"),
                btc_ma_short=(btc_feat or {}).get("ma5"),
                btc_ma_long=(btc_feat or {}).get("ma20"),
                btc_realized_vol_60m=rv,
                vol_high_threshold=vol_hi,
                vol_low_threshold=vol_lo,
                breadth_rising_ratio=breadth,
            )
            regime_at[ts] = reg.value

            # per-symbol features + labels + family hits
            family_cands: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for sym, ser in series_by.items():
                if sym == "KRW-BTC":
                    pass  # still allow BTC as tradable alt? include
                idx = ser["by_min"].get(ts)
                if idx is None:
                    continue
                feat = feature_at(ser, idx)
                if feat is None:
                    continue
                labels = forward_labels(ser, idx)
                # require primary horizon matured
                if labels.get(f"ret_{PRIMARY_HORIZON}m") is None:
                    continue
                hits = evaluate_families(feat, regime=reg)
                row_base = {
                    "ts": ts,
                    "symbol": sym,
                    "regime": reg.value,
                    "feat": feat,
                    "labels": labels,
                }
                for hit in hits:
                    family_cands[hit.family].append(
                        {**row_base, "score": hit.score, "reason": hit.reason}
                    )

            # cross-sectional top-N per family
            for fam, rows in family_cands.items():
                rows.sort(key=lambda r: float(r["score"]), reverse=True)
                for r in rows[:TOP_N_CROSS]:
                    gross = float(r["labels"][f"ret_{PRIMARY_HORIZON}m"])
                    nets = {
                        h: (
                            net_pnl_krw(
                                net_return_pct(
                                    float(r["labels"][f"ret_{h}m"]),
                                    slip_bps=SLIP_BPS_DEFAULT,
                                )
                            )
                            if r["labels"].get(f"ret_{h}m") is not None
                            else None
                        )
                        for h in HORIZONS
                    }
                    opps.append(
                        {
                            "ts": ts.isoformat(),
                            "ts_dt": ts,
                            "symbol": r["symbol"],
                            "family": fam,
                            "score": r["score"],
                            "regime": r["regime"],
                            "gross_primary_pct": gross,
                            "net_primary": nets[PRIMARY_HORIZON],
                            "nets": nets,
                            "mfe": r["labels"].get("mfe"),
                            "mae": r["labels"].get("mae"),
                        }
                    )

        # AI predictive value (existing traces if any)
        ai_rows = session.execute(
            text(
                """
                SELECT UPPER(detail_json->>'ai_recommendation') AS rec,
                       COUNT(*) AS n
                FROM operation.upbit_entry_execution_trace
                WHERE created_at >= :start
                  AND detail_json ? 'ai_recommendation'
                GROUP BY 1
                """
            ),
            {"start": start},
        ).mappings().all()
        ai_dist = {str(r["rec"] or ""): int(r["n"]) for r in ai_rows}

        # Family summaries on full sample (then walk-forward on primary nets)
        by_fam: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for o in opps:
            by_fam[o["family"]].append(o)

        family_results: dict[str, Any] = {}
        fixed_horizon: dict[str, Any] = {}
        for fam in FAMILY_KEYS:
            rows = sorted(by_fam.get(fam, []), key=lambda r: r["ts_dt"])
            nets = [float(r["net_primary"]) for r in rows if r["net_primary"] is not None]
            regs = [r["regime"] for r in rows if r["net_primary"] is not None]
            summary = summarize_nets(nets, days=days, regimes=regs)
            family_results[fam] = summary
            fh = {}
            for h in (15, 30, 60, 120):
                hs = [
                    float(r["nets"][h])
                    for r in rows
                    if r["nets"].get(h) is not None
                ]
                fh[f"NET_{h}M"] = round(sum(hs), 1) if hs else None
                fh[f"AVG_{h}M"] = round(sum(hs) / len(hs), 2) if hs else None
                fh[f"N_{h}M"] = len(hs)
            fixed_horizon[fam] = fh

        # Walk-forward: pick family with best VAL pf among those with val n>=20,
        # report TEST metrics without retuning
        wf_detail: dict[str, Any] = {}
        best_test_name = None
        best_test_sum: dict[str, Any] | None = None
        for fam in FAMILY_KEYS:
            rows = sorted(by_fam.get(fam, []), key=lambda r: r["ts_dt"])
            train, val, test = chronological_splits(rows)
            def _sum(part: list[dict[str, Any]]) -> dict[str, Any]:
                nets = [
                    float(r["net_primary"])
                    for r in part
                    if r["net_primary"] is not None
                ]
                return summarize_nets(nets, days=max(days * len(part) / max(len(rows), 1), 1))

            tr_s, va_s, te_s = _sum(train), _sum(val), _sum(test)
            wf_detail[fam] = {"train": tr_s, "validation": va_s, "test": te_s}
            if int(va_s.get("n") or 0) < 20:
                continue
            if va_s.get("pf") is None:
                continue
            if best_test_sum is None or float(va_s["pf"]) > float(
                best_test_sum.get("_val_pf") or -1
            ):
                best_test_name = fam
                best_test_sum = {**te_s, "_val_pf": va_s["pf"], "_val_n": va_s["n"]}

        # Multi-strategy: families with full-sample pf>1 and total_net>0
        positive_fams = [
            f
            for f, s in family_results.items()
            if f != "M0_CURRENT"
            and (s.get("pf") or 0) >= 1.1
            and (s.get("total_net") or 0) > 0
            and (s.get("n") or 0) >= 30
        ]
        # Dedup by ts+symbol across positive families (keep highest score)
        multi_rows: list[dict[str, Any]] = []
        if positive_fams:
            pool = []
            for f in positive_fams:
                pool.extend(by_fam.get(f, []))
            best: dict[tuple[str, str], dict[str, Any]] = {}
            for r in pool:
                key = (r["ts"], r["symbol"])
                if key not in best or float(r["score"]) > float(best[key]["score"]):
                    best[key] = r
            multi_rows = sorted(best.values(), key=lambda x: x["ts_dt"])
        dup_removed = 0
        if positive_fams:
            raw_n = sum(len(by_fam.get(f, [])) for f in positive_fams)
            dup_removed = max(0, raw_n - len(multi_rows))
        multi_nets = [
            float(r["net_primary"])
            for r in multi_rows
            if r["net_primary"] is not None
        ]
        multi_sum = summarize_nets(
            multi_nets,
            days=days,
            regimes=[r["regime"] for r in multi_rows if r["net_primary"] is not None],
        )
        family_results["BEST_MULTI_STRATEGY"] = multi_sum

        # Slippage sensitivity on best candidate (or M0)
        sens_target = best_test_name or "M0_CURRENT"
        sens_rows = by_fam.get(sens_target, [])
        slip_sens = {}
        for bps in (1.0, 2.0, 5.0):
            nets = []
            for r in sens_rows:
                g = r.get("gross_primary_pct")
                if g is None:
                    continue
                nets.append(
                    net_pnl_krw(net_return_pct(float(g), slip_bps=bps))
                )
            slip_sens[f"{bps}bps"] = summarize_nets(nets, days=days)

        # Classification
        test_ok = False
        if best_test_sum and best_test_name:
            # use TEST metrics for promotion
            test_metrics = {
                k: v
                for k, v in best_test_sum.items()
                if not str(k).startswith("_")
            }
            test_ok = promotion_ok(test_metrics)

        if test_ok and best_test_name:
            classification = "A_POSITIVE_EDGE_FOUND"
        elif best_test_name and int((best_test_sum or {}).get("n") or 0) >= 30:
            classification = "B_PROMISING_BUT_MORE_DATA_REQUIRED"
        else:
            # check if any family full-sample promising but test fails
            any_full = any(
                (s.get("n") or 0) >= 30
                and (s.get("pf") or 0) >= 1.0
                for f, s in family_results.items()
                if f != "BEST_MULTI_STRATEGY"
            )
            if any_full or days < 40:
                classification = "B_PROMISING_BUT_MORE_DATA_REQUIRED"
            else:
                classification = "C_NO_POSITIVE_EDGE_FOUND"

        # Override: if no family meets even weak criteria
        if classification == "A_POSITIVE_EDGE_FOUND":
            pass
        elif not any(
            (s.get("total_net") or 0) > 0 and (s.get("pf") or 0) > 1.0
            for f, s in family_results.items()
            if f not in {"BEST_MULTI_STRATEGY"}
        ):
            if days < 45 or max((s.get("n") or 0) for s in family_results.values()) < 100:
                classification = "B_PROMISING_BUT_MORE_DATA_REQUIRED"
            else:
                classification = "C_NO_POSITIVE_EDGE_FOUND"

        auto_slot = {
            "POSITIVE_STRATEGY_FOUND": classification == "A_POSITIVE_EDGE_FOUND",
            "BROKER_ALL_RESULT": "n/a — no production apply",
            "AUTO_ONLY_RESULT": "deferred until positive edge confirmed",
            "AUTO_ONLY_RECOMMENDED": False,
            "note": "WRK-015: AUTO_ONLY without edge increases loss trades",
        }

        regime_counts = Counter(regime_at.values())

        # Feature quantile peek (volume surge vs 30m net) — descriptive only
        feat_bins = {"volume_surge_decile_avg_net_30m": {}}
        vs_pairs = []
        for fam in ("MOMENTUM", "BREAKOUT", "VOLUME_SURGE"):
            for r in by_fam.get(fam, []):
                # reconstruct surge from score not available — skip detailed
                pass
        # Use opportunities raw with feat if we stored — we didn't keep feat on opps.
        # Lightweight: skip deep feature bins or compute from subset.
        # Re-scan a sample for volume surge deciles from family VOLUME_SURGE/MOMENTUM
        # Already have gross; skip to keep runtime bounded.

        rec = {
            "CLASSIFICATION": classification,
            "RECOMMENDED_ENTRY": best_test_name if test_ok else None,
            "REGIME": None,
            "EXPECTED_TRADES_DAY": (best_test_sum or {}).get("trades_day")
            if test_ok
            else None,
            "EXPECTED_PF": (best_test_sum or {}).get("pf") if test_ok else None,
            "EXPECTED_NET": (best_test_sum or {}).get("total_net")
            if test_ok
            else None,
            "EXPECTED_MDD": (best_test_sum or {}).get("mdd") if test_ok else None,
            "CONFIDENCE": confidence_from_n(int((best_test_sum or {}).get("n") or 0)),
            "RATIONALE": (
                "TEST met promotion criteria"
                if test_ok
                else "No family cleared cost-aware TEST promotion bar; "
                "do not force trades/day target"
            ),
        }
        if test_ok and best_test_name:
            rec["REGIME"] = family_results.get(best_test_name, {}).get(
                "best_regime"
            )

        report = {
            "WORK_ID": WORK_ID,
            "FINAL_VERDICT": "UPBIT_POSITIVE_EDGE_ENTRY_DISCOVERY_COMPLETE",
            "BASE_COMMIT": BASE_COMMIT,
            "RESULT_COMMIT": None,
            "DATA": {
                "WINDOW": window["chosen"],
                "DAYS": days,
                "START": start.isoformat(),
                "END": window["end"].isoformat(),
                "CANDIDATE_SAMPLE": len(opps),
                "MARKET_SAMPLE": len(sample_times) * len(series_by),
                "SAMPLE_TIMES": len(sample_times),
                "SYMBOLS": sorted(series_by.keys()),
                "SYMBOL_COUNT": len(series_by),
                "DATA_QUALITY": (
                    "LIMITED_SPAN_UNDER_90D"
                    if days < 85
                    else "ADEQUATE"
                ),
                "CANDLE_ROWS": window["candle_rows_90d_window"],
                "SAMPLE_EVERY_MIN": SAMPLE_EVERY_MIN,
                "TOP_N_CROSS": TOP_N_CROSS,
                "PRIMARY_HORIZON_MIN": PRIMARY_HORIZON,
                "NOTE": window["note"],
            },
            "COST": {
                "BUY_FEE": FEE_RATE,
                "SELL_FEE": FEE_RATE,
                "SLIPPAGE_BPS_EACH_SIDE": SLIP_BPS_DEFAULT,
                "NOTIONAL_KRW": NOTIONAL,
                "SLIPPAGE_SENSITIVITY": slip_sens,
            },
            "CURRENT": {
                "CURRENT_MA_TPD": family_results.get("M0_CURRENT", {}).get(
                    "trades_day"
                ),
                "CURRENT_MA_PF": family_results.get("M0_CURRENT", {}).get("pf"),
                "CURRENT_MA_NET": family_results.get("M0_CURRENT", {}).get(
                    "total_net"
                ),
                "CURRENT_MA_N": family_results.get("M0_CURRENT", {}).get("n"),
            },
            "REGIME": {
                "BULL": regime_counts.get("BULL_TREND", 0),
                "BEAR": regime_counts.get("BEAR_TREND", 0),
                "SIDEWAYS": regime_counts.get("SIDEWAYS", 0),
                "HIGH_VOL": regime_counts.get("HIGH_VOLATILITY", 0),
                "LOW_VOL": regime_counts.get("LOW_VOLATILITY", 0),
                "vol_thresholds": {"high": vol_hi, "low": vol_lo},
            },
            "ENTRY_FAMILY_RESULTS": family_results,
            "FIXED_HORIZON": fixed_horizon,
            "AI_PREDICTIVE_VALUE": {
                "ALLOW_NET": None,
                "REDUCE_NET": None,
                "CONFIDENCE_CORRELATION": None,
                "AI_HAS_EDGE": None,
                "distribution": ai_dist,
                "note": (
                    "Trace AI labels lack paired future returns in this run; "
                    "distribution only. WRK-015: AI not primary bottleneck."
                ),
            },
            "WALK_FORWARD": {
                "TRAIN": "60%",
                "VALIDATION": "20%",
                "TEST": "20%",
                "detail": wf_detail,
                "BEST_TEST_STRATEGY": best_test_name,
                "TEST_N": (best_test_sum or {}).get("n"),
                "TEST_PF": (best_test_sum or {}).get("pf"),
                "TEST_NET": (best_test_sum or {}).get("total_net"),
                "TEST_MDD": (best_test_sum or {}).get("mdd"),
                "VAL_PF_USED_FOR_SELECTION": (best_test_sum or {}).get("_val_pf"),
            },
            "MULTI_STRATEGY": {
                "COMPONENTS": positive_fams,
                "DUPLICATES_REMOVED": dup_removed,
                "COMBINED_TRADES_DAY": multi_sum.get("trades_day"),
                "COMBINED_PF": multi_sum.get("pf"),
                "COMBINED_NET": multi_sum.get("total_net"),
                "COMBINED_MDD": multi_sum.get("mdd"),
                "COMBINED_N": multi_sum.get("n"),
            },
            "AUTO_SLOT": auto_slot,
            "RECOMMENDATION": rec,
            "PRODUCTION": {
                "REAL_POLICY_CHANGED": False,
                "REAL_ORDER_CREATED_BY_RESEARCH": 0,
                "LIVE_ARM_MUTATION": False,
                "RUNTIME_IMPORT_SAFE": True,
            },
            "REMAINING": (
                "Extend candle history to 60–90d and re-run families; "
                "do not relax M0 thresholds or apply AUTO_ONLY until TEST edge>0"
                if classification != "A_POSITIVE_EDGE_FOUND"
                else "Paper/Shadow approve recommended entry — no REAL yet"
            ),
            "LIMITATIONS": [
                f"Available candle span ~{days:.1f}d (<90d target)",
                "Exact-minute grid may miss sparse symbols",
                "AI future-return pairing incomplete",
                "Cross-section top-3 may still overtrade chop",
            ],
        }

        # Markdown
        lines = [
            "# WRK-016 Upbit Positive-Edge Entry Discovery",
            "",
            f"**Verdict:** `{report['FINAL_VERDICT']}`",
            f"**Classification:** `{classification}`",
            f"**Window:** {window['chosen']} ({days:.1f}d) · opps={len(opps)} · symbols={len(series_by)}",
            "",
            "## Family comparison (cost-aware, primary horizon "
            f"{PRIMARY_HORIZON}m)",
            "",
            "| Strategy | N | Opp/day | Win% | PF | Avg net | Total net | MDD | Best regime | Conf |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
        for fam in list(FAMILY_KEYS) + ["BEST_MULTI_STRATEGY"]:
            s = family_results.get(fam) or {}
            lines.append(
                f"| {fam} | {s.get('n')} | {s.get('trades_day')} | {s.get('win_rate')} | "
                f"{s.get('pf')} | {s.get('avg_net_trade')} | {s.get('total_net')} | "
                f"{s.get('mdd')} | {s.get('best_regime')} | {s.get('confidence')} |"
            )
        lines += [
            "",
            f"## Walk-forward best (by VAL PF): `{best_test_name}`",
            f"- TEST n={ (best_test_sum or {}).get('n') } PF={ (best_test_sum or {}).get('pf') } "
            f"net={ (best_test_sum or {}).get('total_net') }",
            "",
            f"## Recommendation: **{classification}**",
            "",
            str(rec.get("RATIONALE")),
            "",
            f"Next: {report['REMAINING']}",
            "",
            "`REAL_POLICY_CHANGED=false`",
            "",
            "STOP.",
        ]
        OUT_JSON.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        OUT_MD.write_text("\n".join(lines), encoding="utf-8")
        print(
            json.dumps(
                {
                    "verdict": report["FINAL_VERDICT"],
                    "classification": classification,
                    "days": days,
                    "opps": len(opps),
                    "symbols": len(series_by),
                    "best_test": best_test_name,
                    "test_pf": (best_test_sum or {}).get("pf"),
                    "test_net": (best_test_sum or {}).get("total_net"),
                    "m0": family_results.get("M0_CURRENT"),
                    "positive_fams": positive_fams,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
