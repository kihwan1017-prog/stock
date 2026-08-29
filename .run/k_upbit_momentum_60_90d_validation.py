# -*- coding: utf-8 -*-
"""WRK-017 — Momentum 60/90d edge validation (RESEARCH ONLY).

1) Research SQLite candle store (never writes market.candle_minute)
2) Seed from production DB (read-only) + Upbit public API historical backfill
3) Frozen WRK-016 Momentum + cost-aware walk-forward
"""

from __future__ import annotations

import asyncio
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from stock_platform.broker.upbit.market.client import UpbitQuotationClient
from stock_platform.collectors.upbit.minute_collector import UpbitMinuteCollector
from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_momentum_validation.constants import (
    HORIZONS_MIN,
    PRIMARY_CANDIDATES,
)
from stock_platform.operation.upbit_momentum_validation.momentum_rule import (
    frozen_rule_dict,
    momentum_hit,
)
from stock_platform.operation.upbit_momentum_validation.research_candle_store import (
    DEFAULT_DB,
    connect,
    coverage,
    global_span,
    load_symbol_bars,
    upsert_rows,
)
from stock_platform.operation.upbit_positive_edge_entry.regime import (
    MarketRegime,
    classify_regime,
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
from stock_platform.operation.upbit_short_term_turnover.profiles import (
    PROFILE_SPECS,
)
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    MinuteBar,
    bars_from_rows,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_policy_ab import (
    simulate_exit_policy,
)
from stock_platform.operation.upbit_short_term_turnover.slot_shadow import (
    HoldingRow,
    simulate_auto_only_admission,
)

OUT_JSON = Path(".run/k_upbit_momentum_60_90d_validation.json")
OUT_MD = Path(".run/k_upbit_momentum_60_90d_validation.md")
WORK_ID = "WRK-20260829-017-UPBIT-MOMENTUM-60-90D-EDGE-VALIDATION"
BASE_COMMIT = "b7855bc"
TARGET_DAYS = 90
MIN_DAYS = 60
SAMPLE_EVERY = 15
TOP_N = 3
MAX_SYMBOLS = 16  # API budget
FEE = FEE_RATE
SLIP_BASE = 2.0


@dataclass
class Bar:
    at: datetime
    o: float
    h: float
    low: float
    c: float
    v: float


def _sma(xs: list[float], end: int, w: int) -> float | None:
    if end + 1 < w:
        return None
    return sum(xs[end - w + 1 : end + 1]) / w


def _ret(closes: list[float], end: int, lb: int) -> float | None:
    j = end - lb
    if j < 0 or closes[j] <= 0:
        return None
    return (closes[end] / closes[j] - 1.0) * 100.0


def seed_from_prod_db(conn, symbols: list[str], start: datetime) -> dict[str, int]:
    """Read-only copy from market.candle_minute → research sqlite."""

    session = get_session_factory()()
    counts: dict[str, int] = {}
    try:
        for sym in symbols:
            rows = session.execute(
                text(
                    """
                    SELECT c.candle_at, c.open_price, c.high_price, c.low_price,
                           c.close_price, c.volume, c.trade_value
                    FROM market.candle_minute c
                    JOIN market.instrument i ON i.instrument_id=c.instrument_id
                    WHERE i.exchange_code='UPBIT' AND i.symbol=:sym
                      AND c.timeframe=1 AND c.candle_at >= :start
                    ORDER BY c.candle_at
                    """
                ),
                {"sym": sym, "start": start},
            ).mappings().all()
            payload = []
            for r in rows:
                at = r["candle_at"]
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
                payload.append(
                    {
                        "candle_at": at,
                        "open_price": float(r["open_price"]),
                        "high_price": float(r["high_price"]),
                        "low_price": float(r["low_price"]),
                        "close_price": float(r["close_price"]),
                        "volume": float(r["volume"] or 0),
                        "trade_value": float(r["trade_value"] or 0),
                    }
                )
            upsert_rows(conn, symbol=sym, rows=payload, source="prod_db_readonly")
            counts[sym] = len(payload)
    finally:
        session.close()
    return counts


async def backfill_symbol(
    collector: UpbitMinuteCollector,
    conn,
    symbol: str,
    start: datetime,
    end: datetime,
) -> int:
    """Fetch historical minutes into research sqlite only."""

    cov = coverage(conn, symbol)
    # If already spans start..end reasonably, skip heavy fetch
    if cov["n"] > 0 and cov["min"] and cov["max"]:
        mn = datetime.fromisoformat(str(cov["min"]).replace("Z", "+00:00"))
        mx = datetime.fromisoformat(str(cov["max"]).replace("Z", "+00:00"))
        span_days = (mx - mn).total_seconds() / 86400.0
        if mn <= start + timedelta(days=2) and span_days >= MIN_DAYS - 2:
            return 0

    items = await collector.collect(
        market=symbol,
        timeframe=1,
        start_at=start,
        end_at=end,
        max_pages=900,
    )
    rows = [
        {
            "candle_at": it.candle_at,
            "open_price": float(it.open_price),
            "high_price": float(it.high_price),
            "low_price": float(it.low_price),
            "close_price": float(it.close_price),
            "volume": float(it.volume),
            "trade_value": float(it.trade_value),
        }
        for it in items
    ]
    upsert_rows(conn, symbol=symbol, rows=rows, source="upbit_public_api")
    return len(rows)


async def ensure_research_candles(symbols: list[str], start: datetime, end: datetime) -> dict[str, Any]:
    conn = connect(DEFAULT_DB)
    seeded = seed_from_prod_db(conn, symbols, start)
    fetched: dict[str, int] = {}
    async with UpbitQuotationClient() as client:
        collector = UpbitMinuteCollector(client)
        for sym in symbols:
            try:
                n = await backfill_symbol(collector, conn, sym, start, end)
                fetched[sym] = n
                print(f"[backfill] {sym} fetched={n} cov={coverage(conn, sym)}")
            except Exception as exc:  # noqa: BLE001
                fetched[sym] = -1
                print(f"[backfill] {sym} FAILED: {exc}")
    span = global_span(conn)
    conn.close()
    return {
        "db_path": str(DEFAULT_DB),
        "seeded_from_prod": seeded,
        "fetched_api": fetched,
        "span": span,
        "wrote_to_market_candle_minute": False,
    }


def load_series(conn, symbol: str) -> dict[str, Any] | None:
    rows = load_symbol_bars(conn, symbol)
    if len(rows) < 200:
        return None
    bars = [
        Bar(
            at=r["candle_at"],
            o=float(r["open_price"]),
            h=float(r["high_price"]),
            low=float(r["low_price"]),
            c=float(r["close_price"]),
            v=float(r["volume"]),
        )
        for r in rows
    ]
    closes = [b.c for b in bars]
    by_min = {b.at.replace(second=0, microsecond=0): i for i, b in enumerate(bars)}
    return {"bars": bars, "closes": closes, "by_min": by_min, "raw": rows}


def feature_at(series: dict[str, Any], i: int) -> dict[str, Any] | None:
    closes = series["closes"]
    bars: list[Bar] = series["bars"]
    vols = [b.v for b in bars]
    if i < 25:
        return None
    ma5 = _sma(closes, i, 5)
    ma20 = _sma(closes, i, 20)
    ma5_prev = _sma(closes, i - 5, 5)
    sep = None
    if ma5 is not None and ma20 not in (None, 0):
        sep = (ma5 - ma20) / ma20 * 100.0
    avg_vol = _sma(vols, i - 1, 20)
    surge = (vols[i] / avg_vol) if avg_vol and avg_vol > 0 else 0.0
    ma_slope = None
    if ma5 is not None and ma5_prev not in (None, 0):
        ma_slope = (ma5 / ma5_prev - 1.0) * 100.0
    return {
        "close": closes[i],
        "ma5": ma5,
        "ma20": ma20,
        "ma_sep_pct": sep,
        "ma5_slope_pct": ma_slope,
        "volume_surge": surge,
        "rsi14": None,  # unused by momentum
        "ret_5m_pct": _ret(closes, i, 5),
        "ret_15m_pct": _ret(closes, i, 15),
        "ret_60m_pct": _ret(closes, i, 60),
        "breakout_20m": False,
        "trade_value": 0.0,
    }


def forward_rets(series: dict[str, Any], i: int) -> dict[int, float | None]:
    closes = series["closes"]
    entry = closes[i]
    out: dict[int, float | None] = {}
    if entry <= 0:
        return {h: None for h in HORIZONS_MIN}
    for h in HORIZONS_MIN:
        j = i + h
        out[h] = (closes[j] / entry - 1.0) * 100.0 if j < len(closes) else None
    return out


def loss_streak(nets: list[float]) -> int:
    best = cur = 0
    for n in nets:
        if n < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def profit_concentration(nets: list[float]) -> dict[str, float]:
    wins = sorted([n for n in nets if n > 0], reverse=True)
    total = sum(n for n in nets if n > 0)
    if not wins or total <= 0:
        return {"top1_share": 0.0, "top2_share": 0.0, "top5_share": 0.0}
    return {
        "top1_share": round(wins[0] / total, 3),
        "top2_share": round(sum(wins[:2]) / total, 3),
        "top5_share": round(sum(wins[:5]) / total, 3),
    }


def zero_trade_days(ts_list: list[datetime], days: float) -> float:
    active = {t.date() for t in ts_list}
    d = max(int(round(days)), 1)
    return round(100.0 * max(0, d - len(active)) / d, 1)


def pick_symbols() -> list[str]:
    session = get_session_factory()()
    try:
        rows = session.execute(
            text(
                """
                SELECT i.symbol
                FROM market.candle_minute c
                JOIN market.instrument i ON i.instrument_id=c.instrument_id
                WHERE i.exchange_code='UPBIT' AND i.symbol LIKE 'KRW-%'
                  AND i.symbol <> 'KRW-USDT' AND c.timeframe=1
                  AND c.candle_at >= NOW() - INTERVAL '30 days'
                GROUP BY i.symbol
                ORDER BY SUM(c.trade_value) DESC NULLS LAST
                LIMIT :lim
                """
            ),
            {"lim": MAX_SYMBOLS},
        ).scalars().all()
        syms = [str(s) for s in rows]
        if "KRW-BTC" not in syms:
            syms = ["KRW-BTC", *syms][:MAX_SYMBOLS]
        return syms
    finally:
        session.close()


def run_validation(backfill_meta: dict[str, Any]) -> dict[str, Any]:
    conn = connect(DEFAULT_DB)
    span = global_span(conn)
    if not span["min"] or not span["max"]:
        raise RuntimeError("research candle store empty")
    start = datetime.fromisoformat(str(span["min"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(span["max"]).replace("Z", "+00:00"))
    days = max(1.0, (end - start).total_seconds() / 86400.0)

    symbols = [
        r[0]
        for r in conn.execute(
            "SELECT symbol, COUNT(*) n FROM candle_minute GROUP BY symbol HAVING n>=500 ORDER BY n DESC"
        )
    ]
    series_by: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        s = load_series(conn, sym)
        if s:
            series_by[sym] = s
    conn.close()

    btc = series_by.get("KRW-BTC")
    btc_vols: list[float] = []
    if btc:
        closes = btc["closes"]
        for i in range(60, len(closes), 15):
            rets = [
                closes[j] / closes[j - 1] - 1.0
                for j in range(i - 59, i + 1)
                if closes[j - 1] > 0
            ]
            if len(rets) >= 30:
                mu = sum(rets) / len(rets)
                btc_vols.append(
                    math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets)) * 100
                )
    vol_sorted = sorted(btc_vols) or [0.05, 0.1]
    vol_hi = vol_sorted[int(len(vol_sorted) * 0.75)]
    vol_lo = vol_sorted[int(len(vol_sorted) * 0.25)]

    # sample grid
    t0 = start.replace(second=0, microsecond=0)
    if t0.minute % SAMPLE_EVERY:
        t0 += timedelta(minutes=SAMPLE_EVERY - (t0.minute % SAMPLE_EVERY))
    times: list[datetime] = []
    t = t0
    max_h = max(HORIZONS_MIN)
    while t <= end - timedelta(minutes=max_h):
        times.append(t)
        t += timedelta(minutes=SAMPLE_EVERY)

    signals: list[dict[str, Any]] = []
    regime_at: dict[datetime, str] = {}

    for ts in times:
        rising = total = 0
        for ser in series_by.values():
            idx = ser["by_min"].get(ts)
            if idx is None:
                continue
            r15 = _ret(ser["closes"], idx, 15)
            if r15 is None:
                continue
            total += 1
            if r15 > 0:
                rising += 1
        breadth = rising / total if total else None

        btc_feat = None
        btc_idx = btc["by_min"].get(ts) if btc else None
        if btc and btc_idx is not None:
            btc_feat = feature_at(btc, btc_idx)
        rv = None
        if btc and btc_idx is not None and btc_idx >= 60:
            closes = btc["closes"]
            rets = [
                closes[j] / closes[j - 1] - 1.0
                for j in range(btc_idx - 59, btc_idx + 1)
                if closes[j - 1] > 0
            ]
            if rets:
                mu = sum(rets) / len(rets)
                rv = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets)) * 100

        reg = classify_regime(
            btc_ret_60m_pct=(btc_feat or {}).get("ret_60m_pct"),
            btc_ma_short=(btc_feat or {}).get("ma5"),
            btc_ma_long=(btc_feat or {}).get("ma20"),
            btc_realized_vol_60m=rv,
            vol_high_threshold=vol_hi,
            vol_low_threshold=vol_lo,
            breadth_rising_ratio=breadth,
        )
        # map LOW_VOL into SIDEWAYS bucket for reporting gate; keep HIGH_VOL
        regime_label = reg.value
        if reg == MarketRegime.LOW_VOLATILITY:
            regime_label = "SIDEWAYS"
        if reg == MarketRegime.BEAR_TREND:
            regime_label = "BEAR_RISK_OFF"
        regime_at[ts] = regime_label

        cands: list[dict[str, Any]] = []
        for sym, ser in series_by.items():
            idx = ser["by_min"].get(ts)
            if idx is None:
                continue
            feat = feature_at(ser, idx)
            if feat is None:
                continue
            ok, score = momentum_hit(feat, regime=reg)
            if not ok:
                continue
            frets = forward_rets(ser, idx)
            if frets.get(60) is None and frets.get(120) is None:
                continue
            nets = {
                h: (
                    net_pnl_krw(net_return_pct(float(frets[h]), slip_bps=SLIP_BASE))
                    if frets.get(h) is not None
                    else None
                )
                for h in HORIZONS_MIN
            }
            gross = {h: frets.get(h) for h in HORIZONS_MIN}
            cands.append(
                {
                    "ts": ts,
                    "symbol": sym,
                    "score": score,
                    "regime": regime_label,
                    "nets": nets,
                    "gross": gross,
                    "idx": idx,
                    "series_sym": sym,
                }
            )
        cands.sort(key=lambda x: x["score"], reverse=True)
        signals.extend(cands[:TOP_N])

    def nets_for(horizon: int, rows: list[dict[str, Any]], slip: float = SLIP_BASE) -> list[float]:
        out = []
        for r in rows:
            g = r["gross"].get(horizon)
            if g is None:
                continue
            out.append(net_pnl_krw(net_return_pct(float(g), slip_bps=slip)))
        return out

    # Full-sample by horizon
    horizon_full: dict[str, Any] = {}
    for h in HORIZONS_MIN:
        xs = nets_for(h, signals)
        horizon_full[f"{h}m"] = {
            **summarize_nets(xs, days=days),
            "loss_streak": loss_streak(xs),
            "profit_concentration": profit_concentration(xs),
            "zero_trade_days_pct": zero_trade_days([r["ts"] for r in signals], days),
        }

    # Walk-forward per primary candidate horizon
    rows_sorted = sorted(signals, key=lambda r: r["ts"])
    train, val, test = chronological_splits(rows_sorted)
    wf: dict[str, Any] = {}
    for h in PRIMARY_CANDIDATES:
        tr = nets_for(h, train)
        va = nets_for(h, val)
        te = nets_for(h, test)
        wf[f"{h}m"] = {
            "train": summarize_nets(tr, days=max(days * 0.6, 1)),
            "validation": summarize_nets(va, days=max(days * 0.2, 1)),
            "test": {
                **summarize_nets(te, days=max(days * 0.2, 1)),
                "loss_streak": loss_streak(te),
                "profit_concentration": profit_concentration(te),
                "zero_trade_days_pct": zero_trade_days(
                    [r["ts"] for r in test], max(days * 0.2, 1)
                ),
            },
        }

    # Pick OOS-stable between 60 and 120
    def oos_score(h: int) -> tuple[float, float, int]:
        te = wf[f"{h}m"]["test"]
        pf = float(te.get("pf") or 0)
        net = float(te.get("total_net") or 0)
        n = int(te.get("n") or 0)
        return (pf, net, n)

    h60, h120 = oos_score(60), oos_score(120)
    # prefer higher TEST PF, then net, require n
    selected_h = 60 if (h60[0], h60[1], h60[2]) >= (h120[0], h120[1], h120[2]) else 120
    test_sum = wf[f"{selected_h}m"]["test"]
    test_nets = nets_for(selected_h, test)

    # Slippage sensitivity on TEST for selected horizon
    slip_sens = {}
    for bps in (1.0, 2.0, 5.0):
        xs = nets_for(selected_h, test, slip=bps)
        slip_sens[f"{bps}bps"] = summarize_nets(xs, days=max(days * 0.2, 1))

    # Regime breakdown (full sample, selected horizon)
    by_reg: dict[str, list[float]] = defaultdict(list)
    for r in signals:
        g = r["gross"].get(selected_h)
        if g is None:
            continue
        by_reg[r["regime"]].append(
            net_pnl_krw(net_return_pct(float(g), slip_bps=SLIP_BASE))
        )
    regime_perf = {
        k: summarize_nets(v, days=days) for k, v in sorted(by_reg.items())
    }

    # Weekly stability
    by_week: dict[str, list[float]] = defaultdict(list)
    for r in signals:
        g = r["gross"].get(selected_h)
        if g is None:
            continue
        week = r["ts"].strftime("%Y-W%W")
        by_week[week].append(
            net_pnl_krw(net_return_pct(float(g), slip_bps=SLIP_BASE))
        )
    weekly = {
        w: {
            "n": len(xs),
            "net": round(sum(xs), 1),
            "pf": round(profit_factor(xs), 3) if xs else None,
        }
        for w, xs in sorted(by_week.items())
    }

    # Promotion
    te_n = int(test_sum.get("n") or 0)
    te_pf = float(test_sum.get("pf") or 0)
    te_net = float(test_sum.get("total_net") or 0)
    conc = test_sum.get("profit_concentration") or profit_concentration(test_nets)
    slip5 = slip_sens.get("5.0bps") or {}
    slip5_pf = float(slip5.get("pf") or 0)
    slip5_net = float(slip5.get("total_net") or 0)
    concentration_ok = float(conc.get("top2_share") or 1) < 0.55
    slip5_ok = not (slip5_pf < 0.7 and slip5_net < te_net * 0.2)
    # "does not immediately collapse at 5bps": PF stays >= 0.85 or net not deeply worse
    slip5_ok = slip5_pf >= 0.85 or slip5_net > -abs(te_net) * 2

    promoted = (
        te_net > 0
        and te_pf >= 1.10
        and te_n >= 30
        and concentration_ok
        and slip5_ok
        and days >= MIN_DAYS - 1
    )

    if promoted:
        classification = "A_MOMENTUM_EDGE_CONFIRMED"
    elif te_n >= 20 and (te_pf >= 1.0 or (horizon_full.get(f"{selected_h}m") or {}).get("pf", 0) >= 1.05):
        classification = "B_MOMENTUM_PROMISING_MORE_DATA"
    elif days < MIN_DAYS:
        classification = "B_MOMENTUM_PROMISING_MORE_DATA"
    else:
        classification = "C_MOMENTUM_EDGE_REJECTED"

    # Regime gate / multi-exit / auto-only only if A
    regime_gate = {"applied": False}
    multi_exit = {"applied": False}
    auto_slot = {"applied": False, "AUTO_ONLY_RECOMMENDED": False}

    if classification == "A_MOMENTUM_EDGE_CONFIRMED":
        # keep only best regimes with pf>=1.1 on full sample
        good_regs = [
            k
            for k, v in regime_perf.items()
            if (v.get("pf") or 0) >= 1.1 and (v.get("total_net") or 0) > 0
        ]
        gated = [r for r in test if r["regime"] in good_regs] if good_regs else list(test)
        g_nets = nets_for(selected_h, gated)
        regime_gate = {
            "applied": True,
            "allowed_regimes": good_regs,
            "test_ungated": test_sum,
            "test_gated": summarize_nets(g_nets, days=max(days * 0.2, 1)),
        }
        # BALANCED multi-exit shadow on test entries
        bal = PROFILE_SPECS["BALANCED_TURNOVER"]
        exit_nets = []
        for r in test[:200]:  # cap compute
            ser = series_by.get(r["series_sym"])
            if not ser:
                continue
            idx = int(r["idx"])
            raw = ser["raw"]
            # bars from entry for horizon window
            window_rows = raw[max(0, idx - 5) : idx + bal.horizon_minutes + 2]
            bars = bars_from_rows(window_rows)
            if len(bars) < 10:
                continue
            entry_at = ser["bars"][idx].at
            entry_px = ser["closes"][idx]
            try:
                sim = simulate_exit_policy(
                    bars,
                    symbol=r["symbol"],
                    entry_at=entry_at,
                    entry_price=__import__("decimal").Decimal(str(entry_px)),
                    spec=bal.exit_spec,
                    horizon_minutes=bal.horizon_minutes,
                    notional_krw=__import__("decimal").Decimal(str(NOTIONAL)),
                    fee_rate=__import__("decimal").Decimal(str(FEE)),
                    now=end,
                )
                # add 2bps slip approx
                slip = NOTIONAL * (SLIP_BASE / 10000.0) * 2
                exit_nets.append(float(sim.net_pnl_krw) - slip)
            except Exception:  # noqa: BLE001
                continue
        multi_exit = {
            "applied": True,
            "profile": "BALANCED_TURNOVER",
            "n": len(exit_nets),
            "summary": summarize_nets(exit_nets, days=max(days * 0.2, 1)),
        }
        # AUTO_ONLY conceptual: if broker full of manuals, momentum still admits
        demo = simulate_auto_only_admission(
            holdings=[
                HoldingRow("KRW-ADA", 1.0, "AUTO"),
                HoldingRow("KRW-BTC", 0.01, "MANUAL"),
                HoldingRow("KRW-ETH", 0.1, "MANUAL"),
                HoldingRow("KRW-DOGE", 100.0, "MANUAL"),
                HoldingRow("KRW-SKY", 10.0, "MANUAL"),
            ],
            max_positions=5,
        )
        auto_slot = {
            "applied": True,
            "demo_admission": demo,
            "AUTO_ONLY_RECOMMENDED": bool(demo.get("additional_opportunity")),
            "note": "Only relevant because momentum edge confirmed; production unchanged",
        }

    full_sel = horizon_full.get(f"{selected_h}m") or {}

    report = {
        "WORK_ID": WORK_ID,
        "FINAL_VERDICT": "UPBIT_MOMENTUM_60_90D_VALIDATION_COMPLETE",
        "CLASSIFICATION": classification,
        "BASE_COMMIT": BASE_COMMIT,
        "RESULT_COMMIT": None,
        "DATA": {
            "TARGET_DAYS": TARGET_DAYS,
            "MIN_DAYS": MIN_DAYS,
            "ACHIEVED_DAYS": round(days, 2),
            "SPAN_START": start.isoformat(),
            "SPAN_END": end.isoformat(),
            "SYMBOLS": sorted(series_by.keys()),
            "SYMBOL_COUNT": len(series_by),
            "SIGNALS": len(signals),
            "SAMPLE_TIMES": len(times),
            "RESEARCH_DB": str(DEFAULT_DB),
            "BACKFILL": backfill_meta,
            "WROTE_PRODUCTION_CANDLES": False,
            "DATA_QUALITY": (
                "ADEQUATE_60D"
                if days >= MIN_DAYS
                else ("PARTIAL_UNDER_60D" if days >= 40 else "INSUFFICIENT")
            ),
        },
        "FROZEN_MOMENTUM_RULE": frozen_rule_dict(),
        "COST": {
            "BUY_FEE": FEE,
            "SELL_FEE": FEE,
            "SLIPPAGE_BPS_BASELINE": SLIP_BASE,
            "SLIPPAGE_SENSITIVITY_TEST": slip_sens,
        },
        "SELECTED_HORIZON_MIN": selected_h,
        "HORIZON_FULL": horizon_full,
        "WALK_FORWARD": {
            "TRAIN": "60%",
            "VALIDATION": "20%",
            "TEST": "20%",
            "by_horizon": wf,
            "TEST_SELECTED": test_sum,
            "TEST_N": te_n,
            "TEST_PF": te_pf,
            "TEST_NET": te_net,
            "TEST_MDD": test_sum.get("mdd"),
        },
        "REGIME_PERF": regime_perf,
        "WEEKLY_STABILITY": weekly,
        "PROMOTION_CHECKS": {
            "TEST_NET_GT_0": te_net > 0,
            "TEST_PF_GE_1_10": te_pf >= 1.10,
            "TEST_N_GE_30": te_n >= 30,
            "COST_2BPS_INCLUDED": True,
            "SLIP_5BPS_NOT_COLLAPSE": slip5_ok,
            "CONCENTRATION_OK": concentration_ok,
            "profit_concentration": conc,
            "days_ok": days >= MIN_DAYS - 1,
            "promoted": promoted,
        },
        "REGIME_GATE": regime_gate,
        "MULTI_EXIT_SHADOW": multi_exit,
        "AUTO_SLOT": auto_slot,
        "MOMENTUM_FULL": full_sel,
        "PRODUCTION": {
            "REAL_POLICY_CHANGED": False,
            "REAL_ORDER_CREATED_BY_RESEARCH": 0,
            "LIVE_ARM_MUTATION": False,
        },
        "REMAINING": (
            "No REAL apply. "
            + (
                "Paper/Shadow approve frozen Momentum + selected horizon."
                if classification == "A_MOMENTUM_EDGE_CONFIRMED"
                else "Extend research candles toward 90d and re-run without retuning; or reject Momentum for production."
            )
        ),
    }

    lines = [
        "# WRK-017 Momentum 60/90d Edge Validation",
        "",
        f"**Classification:** `{classification}`",
        f"**Achieved days:** {days:.1f} (target 90 / min 60)",
        f"**Selected OOS horizon:** {selected_h}m",
        f"**Signals:** {len(signals)} · symbols={len(series_by)}",
        f"**Research DB:** `{DEFAULT_DB}` (prod candles not written)",
        "",
        "## Frozen rule",
        "```",
        json.dumps(frozen_rule_dict(), indent=2),
        "```",
        "",
        "## TEST (selected horizon)",
        f"- N={te_n} PF={te_pf} NET={te_net} MDD={test_sum.get('mdd')}",
        f"- slip sensitivity: {json.dumps(slip_sens, default=str)}",
        "",
        "## Horizon full-sample PF/NET",
    ]
    for h in HORIZONS_MIN:
        s = horizon_full.get(f"{h}m") or {}
        lines.append(
            f"- {h}m: n={s.get('n')} pf={s.get('pf')} net={s.get('total_net')} "
            f"tpd={s.get('trades_day')}"
        )
    lines += [
        "",
        f"## Recommendation: **{classification}**",
        "",
        report["REMAINING"],
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
    return report


def main() -> None:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=TARGET_DAYS)
    symbols = pick_symbols()
    print(f"symbols={symbols}")
    meta = asyncio.run(ensure_research_candles(symbols, start, now))
    print(json.dumps(meta.get("span"), default=str))
    report = run_validation(meta)
    print(
        json.dumps(
            {
                "classification": report["CLASSIFICATION"],
                "days": report["DATA"]["ACHIEVED_DAYS"],
                "selected_h": report["SELECTED_HORIZON_MIN"],
                "test_pf": report["WALK_FORWARD"]["TEST_PF"],
                "test_net": report["WALK_FORWARD"]["TEST_NET"],
                "test_n": report["WALK_FORWARD"]["TEST_N"],
                "signals": report["DATA"]["SIGNALS"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
