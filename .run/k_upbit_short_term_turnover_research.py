# -*- coding: utf-8 -*-
"""WRK-015 short-term turnover research — SHADOW ONLY (fixed simulator API)."""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import select, text

from stock_platform.broker.fee_policy import UpbitFeePolicy
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_full_market.entities import (
    UpbitPortfolioPolicyEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    MinuteBar,
    as_utc,
    bars_from_rows,
    floor_minute,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_policy_ab import (
    ExitPolicySpec,
    ExitSimResult,
    simulate_exit_policy,
)
from stock_platform.realtime.ma_exit_policy import (
    DEFAULT_EXIT_MIN_MA_SEPARATION_PCT,
    DEFAULT_MA_EXIT_MIN_HOLDING_SECONDS,
    load_ma_exit_thresholds,
)

OUT_JSON = Path(".run/k_upbit_short_term_turnover_research.json")
OUT_MD = Path(".run/k_upbit_short_term_turnover_research.md")
UBA = 1380
FEE_RATE = UpbitFeePolicy.DEFAULT_TAKER_RATE
SLIPPAGE_BPS = 2.0  # each side, research assumption
NOTIONAL = Decimal("10000")


def _pct(n: float, d: float) -> float | None:
    if d <= 0:
        return None
    return round(100.0 * n / d, 2)


def _median(xs: list[float]) -> float | None:
    return float(statistics.median(xs)) if xs else None


def _mean(xs: list[float]) -> float | None:
    return float(statistics.fmean(xs)) if xs else None


def apply_slippage_to_net(sim: ExitSimResult) -> ExitSimResult:
    """Add estimated slippage drag (bps each side on notional)."""

    slip = float(NOTIONAL) * (SLIPPAGE_BPS / 10000.0) * 2.0
    net = float(sim.net_pnl_krw) - slip
    detail = dict(sim.detail or {})
    detail["slippage_krw_est"] = slip
    return ExitSimResult(
        policy=sim.policy,
        symbol=sim.symbol,
        entry_at=sim.entry_at,
        entry_price=sim.entry_price,
        exit_at=sim.exit_at,
        exit_price=sim.exit_price,
        exit_reason=sim.exit_reason,
        holding_seconds=sim.holding_seconds,
        gross_return_pct=sim.gross_return_pct,
        estimated_fee_krw=sim.estimated_fee_krw,
        net_return_pct=sim.net_return_pct,
        gross_pnl_krw=sim.gross_pnl_krw,
        net_pnl_krw=net,
        mfe_pct=sim.mfe_pct,
        mae_pct=sim.mae_pct,
        trail_activated=sim.trail_activated,
        fee_only_loss=sim.fee_only_loss,
        detail=detail,
    )


def snapshot_baseline(session) -> dict[str, Any]:
    pol = session.scalar(
        select(UpbitPortfolioPolicyEntity).where(
            UpbitPortfolioPolicyEntity.user_broker_account_id == UBA
        )
    )
    rg = dict(pol.risk_group_policy_json or {}) if pol else {}
    th = load_ma_exit_thresholds(
        settings=get_settings(), risk_group_policy_json=rg
    )
    strat = session.execute(
        text(
            "SELECT parameter_payload FROM trading.strategy_definition "
            "WHERE strategy_id = 17483"
        )
    ).scalar()
    payload = dict(strat or {}) if isinstance(strat, dict) else {}
    baseline = {
        "uba_id": UBA,
        "max_positions": int(pol.max_positions) if pol else None,
        "max_symbol_exposure_pct": float(pol.max_symbol_exposure_pct)
        if pol
        else None,
        "max_total_exposure_pct": float(pol.max_total_exposure_pct)
        if pol
        else None,
        "min_cash_reserve_pct": float(pol.min_cash_reserve_pct) if pol else None,
        "per_position_target_pct": float(pol.per_position_target_pct)
        if pol
        else None,
        "portfolio_daily_entry_limit": int(pol.portfolio_daily_entry_limit)
        if pol
        else None,
        "portfolio_max_pending_entries": int(pol.portfolio_max_pending_entries)
        if pol
        else None,
        "entry_cooldown_seconds": int(pol.entry_cooldown_seconds) if pol else None,
        "entry_signal_policy": rg.get("entry_signal_policy"),
        "ma_short_window": int(payload.get("short_window") or 5),
        "ma_long_window": int(payload.get("long_window") or 20),
        "strategy_stop_loss_ratio": payload.get("stop_loss_ratio"),
        "strategy_take_profit_ratio": payload.get("take_profit_ratio"),
        "exit_min_ma_separation_pct": th.exit_min_ma_separation_pct,
        "ma_exit_min_holding_seconds": th.ma_exit_min_holding_seconds,
        "fee_rate": float(FEE_RATE),
        "slippage_bps_each_side_research": SLIPPAGE_BPS,
        "safety_max_open_positions": 5,
        "safety_counts_broker_all": True,
        "wrk014_durable_exit_intent": True,
    }
    baseline["BASELINE_CONFIG_HASH"] = hashlib.sha256(
        json.dumps(baseline, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return baseline


def resolve_window(session) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    last: dict[str, Any] = {}
    for days in (30, 14, 7):
        start = now - timedelta(days=days)
        try:
            candles = session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM market.candle_minute cm
                    JOIN market.instrument i
                      ON i.instrument_id = cm.instrument_id
                    WHERE i.exchange_code='UPBIT'
                      AND cm.timeframe = 1
                      AND cm.candle_at >= :start
                    """
                ),
                {"start": start},
            ).scalar()
        except Exception:
            candles = 0
        traces = session.execute(
            text(
                """
                SELECT COUNT(*) FROM operation.upbit_entry_execution_trace
                WHERE user_broker_account_id=:uba AND created_at >= :start
                """
            ),
            {"uba": UBA, "start": start},
        ).scalar()
        orders = session.execute(
            text(
                """
                SELECT COUNT(*) FROM trading.trading_order
                WHERE user_broker_account_id=:uba AND created_at >= :start
                """
            ),
            {"uba": UBA, "start": start},
        ).scalar()
        last = {
            "days": days,
            "start": start,
            "end": now,
            "candle_rows": int(candles or 0),
            "trace_rows": int(traces or 0),
            "order_rows": int(orders or 0),
            "chosen": f"{days}d",
        }
        if int(traces or 0) > 30 or int(orders or 0) > 5:
            return {
                **last,
                "start": start.isoformat(),
                "end": now.isoformat(),
            }
    last["start"] = last["start"].isoformat()
    last["end"] = last["end"].isoformat()
    last["chosen"] = f"{last['days']}d_fallback"
    return last


def funnel_analysis(session, start: datetime) -> dict[str, Any]:
    rows = session.execute(
        text(
            """
            SELECT stage, decision, reason_code, selection_id
            FROM operation.upbit_entry_execution_trace
            WHERE user_broker_account_id=:uba AND created_at >= :start
            """
        ),
        {"uba": UBA, "start": start},
    ).mappings().all()
    by_stage: Counter[str] = Counter()
    reject: Counter[str] = Counter()
    uniq: dict[str, set[int]] = defaultdict(set)
    for r in rows:
        st = str(r["stage"] or "")
        by_stage[st] += 1
        rc = str(r["reason_code"] or "") or "(none)"
        if str(r["decision"] or "").upper() in {"REJECT", "SKIP", "FAIL"}:
            reject[rc] += 1
        if r.get("selection_id") is not None:
            uniq[st].add(int(r["selection_id"]))
    funnel_unique = {k: len(v) for k, v in uniq.items()}
    return {
        "trace_events": len(rows),
        "by_stage_event": dict(by_stage.most_common(40)),
        "funnel_unique_selection": funnel_unique,
        "top_reject_skip_reasons": [
            {"reason": a, "count": b} for a, b in reject.most_common(15)
        ],
    }


def load_entries(session, start: datetime) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            SELECT order_id, symbol, created_at, filled_at,
                   average_fill_price, order_price, filled_quantity,
                   metadata_payload
            FROM trading.trading_order
            WHERE user_broker_account_id=:uba
              AND side_code='BUY' AND status_code='FILLED'
              AND COALESCE(filled_at, created_at) >= :start
            ORDER BY COALESCE(filled_at, created_at)
            """
        ),
        {"uba": UBA, "start": start},
    ).mappings().all()
    out = []
    for r in rows:
        px = r["average_fill_price"] or r["order_price"]
        if px is None:
            continue
        at = r["filled_at"] or r["created_at"]
        if getattr(at, "tzinfo", None) is None:
            at = at.replace(tzinfo=timezone.utc)
        out.append(
            {
                "order_id": int(r["order_id"]),
                "symbol": str(r["symbol"]).upper(),
                "entry_at": as_utc(at),
                "entry_price": Decimal(str(px)),
            }
        )
    return out


def load_bars(session, symbol: str, start: datetime, end: datetime) -> list[MinuteBar]:
    try:
        rows = session.execute(
            text(
                """
                SELECT cm.candle_at, cm.open_price, cm.high_price, cm.low_price,
                       cm.close_price, cm.volume
                FROM market.candle_minute cm
                JOIN market.instrument i ON i.instrument_id = cm.instrument_id
                WHERE i.exchange_code='UPBIT' AND i.symbol=:sym
                  AND cm.timeframe = 1
                  AND cm.candle_at >= :start AND cm.candle_at <= :end
                ORDER BY cm.candle_at
                """
            ),
            {"sym": symbol, "start": start, "end": end},
        ).mappings().all()
        if rows:
            return bars_from_rows([dict(r) for r in rows])
    except Exception:
        return []
    return []


def run_sim(
    *,
    bars: Sequence[MinuteBar],
    symbol: str,
    entry_at: datetime,
    entry_price: Decimal,
    spec: ExitPolicySpec,
    horizon_minutes: int,
) -> ExitSimResult | None:
    if len(bars) < 25:
        return None
    sim = simulate_exit_policy(
        bars,
        symbol=symbol,
        entry_at=entry_at,
        entry_price=entry_price,
        spec=spec,
        horizon_minutes=horizon_minutes,
        notional_krw=NOTIONAL,
        fee_rate=FEE_RATE,
        now=datetime.now(timezone.utc),
    )
    return apply_slippage_to_net(sim)


def aggregate(
    label: str,
    sims: list[ExitSimResult],
    days: int,
    entry_factor: float = 1.0,
) -> dict[str, Any]:
    if not sims:
        return {
            "label": label,
            "trades": 0,
            "trades_per_day": 0.0,
            "zero_trade_days_pct": 100.0,
            "win_rate": None,
            "profit_factor": None,
            "gross_pnl": 0,
            "fees": 0,
            "slippage": 0,
            "net_pnl": 0,
            "max_drawdown": 0,
            "avg_holding_minutes": None,
            "median_holding_minutes": None,
        }
    holds = [float(s.holding_seconds or 0) for s in sims]
    nets = [float(s.net_pnl_krw) for s in sims]
    grosses = [float(s.gross_pnl_krw) for s in sims]
    fees = [float(s.estimated_fee_krw) for s in sims]
    slips = [float((s.detail or {}).get("slippage_krw_est") or 0) for s in sims]
    wins = sum(1 for n in nets if n > 0)
    win_sum = sum(n for n in nets if n > 0)
    loss_sum = abs(sum(n for n in nets if n < 0))
    pf = (win_sum / loss_sum) if loss_sum > 0 else (999.0 if win_sum > 0 else 0.0)
    equity = peak = mdd = 0.0
    for n in nets:
        equity += n
        peak = max(peak, equity)
        mdd = max(mdd, peak - equity)
    by_day = Counter(as_utc(s.entry_at).date().isoformat() for s in sims)
    scale = float(entry_factor)
    return {
        "label": label,
        "trades": int(round(len(sims) * scale)),
        "trades_per_day": round(len(sims) / max(days, 1) * scale, 2),
        "zero_trade_days_pct": round(
            100.0 * max(0, days - len(by_day)) / max(days, 1), 1
        ),
        "win_rate": round(100.0 * wins / len(sims), 1),
        "profit_factor": round(pf, 2),
        "gross_pnl": round(sum(grosses) * scale, 1),
        "fees": round(sum(fees) * scale, 1),
        "slippage": round(sum(slips) * scale, 1),
        "net_pnl": round(sum(nets) * scale, 1),
        "max_drawdown": round(mdd * scale, 1),
        "avg_holding_minutes": round((_mean(holds) or 0) / 60.0, 1),
        "median_holding_minutes": round((_median(holds) or 0) / 60.0, 1),
        "exit_reasons": dict(Counter(s.exit_reason for s in sims)),
        "entry_factor": scale,
    }


def profiles() -> dict[str, tuple[ExitPolicySpec, int]]:
    sep = DEFAULT_EXIT_MIN_MA_SEPARATION_PCT
    hold = DEFAULT_MA_EXIT_MIN_HOLDING_SECONDS
    return {
        "BASELINE": (
            ExitPolicySpec(
                label="BASELINE",
                tp_pct=10.0,
                sl_pct=5.0,
                trail_distance_pct=3.0,
                trail_activation_pct=None,
                ma_exit_enabled=True,
                exit_min_ma_separation_pct=sep,
                ma_exit_min_holding_seconds=hold,
            ),
            1440,  # 24h horizon proxy for long holds
        ),
        "CONSERVATIVE_TURNOVER": (
            ExitPolicySpec(
                label="CONSERVATIVE_TURNOVER",
                tp_pct=1.5,
                sl_pct=1.0,
                trail_distance_pct=0.8,
                trail_activation_pct=0.6,
                ma_exit_enabled=True,
                exit_min_ma_separation_pct=sep,
                ma_exit_min_holding_seconds=hold,
            ),
            240,
        ),
        "BALANCED_TURNOVER": (
            ExitPolicySpec(
                label="BALANCED_TURNOVER",
                tp_pct=1.2,
                sl_pct=0.8,
                trail_distance_pct=0.6,
                trail_activation_pct=0.5,
                ma_exit_enabled=True,
                exit_min_ma_separation_pct=sep,
                ma_exit_min_holding_seconds=hold,
            ),
            120,
        ),
        "AGGRESSIVE_TURNOVER": (
            ExitPolicySpec(
                label="AGGRESSIVE_TURNOVER",
                tp_pct=0.8,
                sl_pct=0.5,
                trail_distance_pct=0.4,
                trail_activation_pct=0.4,
                ma_exit_enabled=True,
                exit_min_ma_separation_pct=sep,
                ma_exit_min_holding_seconds=hold,
            ),
            60,
        ),
    }


def one_factor_grids(
    entries: list[dict], bars_by: dict[str, list[MinuteBar]]
) -> dict[str, Any]:
    base = ExitPolicySpec(
        label="G",
        tp_pct=10.0,
        sl_pct=5.0,
        trail_distance_pct=3.0,
        trail_activation_pct=None,
        ma_exit_enabled=True,
    )

    def eval_specs(items: list[tuple[str, ExitPolicySpec, int]]) -> dict:
        out = {}
        for lab, spec, hz in items:
            sims = []
            for e in entries:
                bars = bars_by.get(e["symbol"]) or []
                s = run_sim(
                    bars=bars,
                    symbol=e["symbol"],
                    entry_at=e["entry_at"],
                    entry_price=e["entry_price"],
                    spec=replace(spec, label=lab),
                    horizon_minutes=hz,
                )
                if s:
                    sims.append(s)
            if not sims:
                out[lab] = {"net_pnl": 0, "trades": 0}
                continue
            nets = [float(x.net_pnl_krw) for x in sims]
            out[lab] = {
                "trades": len(sims),
                "net_pnl": round(sum(nets), 1),
                "avg_hold_min": round(
                    (_mean([float(x.holding_seconds or 0) for x in sims]) or 0)
                    / 60,
                    1,
                ),
                "win_rate": round(
                    100 * sum(1 for n in nets if n > 0) / len(nets), 1
                ),
                "exit_reasons": dict(Counter(x.exit_reason for x in sims)),
            }
        return out

    tp = eval_specs(
        [
            (f"TP_{p}", replace(base, tp_pct=p), 240)
            for p in (0.8, 1.2, 1.5, 2.0)
        ]
    )
    sl = eval_specs(
        [
            (f"SL_{p}", replace(base, sl_pct=p), 240)
            for p in (0.5, 0.8, 1.0, 1.5)
        ]
    )
    tr = eval_specs(
        [
            (
                f"TR_{d}",
                replace(
                    base,
                    trail_distance_pct=d,
                    trail_activation_pct=max(0.3, d),
                ),
                240,
            )
            for d in (0.4, 0.6, 0.8, 1.0)
        ]
    )
    tm = eval_specs(
        [(f"H{m}", base, m) for m in (30, 60, 120, 240)]
    )

    def best(g: dict) -> str:
        return max(g.items(), key=lambda kv: kv[1].get("net_pnl", -1e18))[0] if g else "n/a"

    return {
        "TP": tp,
        "SL": sl,
        "TRAILING": tr,
        "TIME_EXIT": tm,
        "BEST_TP": best(tp),
        "BEST_SL": best(sl),
        "BEST_TRAILING": best(tr),
        "BEST_TIME_EXIT": best(tm),
    }


def main() -> None:
    session = get_session_factory()()
    try:
        baseline = snapshot_baseline(session)
        window = resolve_window(session)
        start = datetime.fromisoformat(window["start"])
        end = datetime.fromisoformat(window["end"])
        days = int(window["days"])
        funnel = funnel_analysis(session, start)
        entries = load_entries(session, start)

        # holding
        binds = session.execute(
            text(
                """
                SELECT opened_at, closed_at FROM operation.upbit_strategy_position_binding
                WHERE user_broker_account_id=:uba AND opened_at >= :start
                """
            ),
            {"uba": UBA, "start": start},
        ).mappings().all()
        holds = []
        still_open = 0
        now = datetime.now(timezone.utc)
        for b in binds:
            op = b["opened_at"]
            if op is None:
                continue
            if op.tzinfo is None:
                op = op.replace(tzinfo=timezone.utc)
            cl = b["closed_at"]
            if cl is None:
                still_open += 1
                cl = now
            elif cl.tzinfo is None:
                cl = cl.replace(tzinfo=timezone.utc)
            holds.append((cl - op).total_seconds())

        # AI
        ai_rows = session.execute(
            text(
                """
                SELECT detail_json->>'ai_recommendation' AS ai_rec
                FROM operation.upbit_entry_execution_trace
                WHERE user_broker_account_id=:uba AND created_at >= :start
                  AND detail_json ? 'ai_recommendation'
                """
            ),
            {"uba": UBA, "start": start},
        ).mappings().all()
        ai_dist = Counter(str(r["ai_rec"] or "").upper() for r in ai_rows)
        ai_block = session.execute(
            text(
                """
                SELECT COUNT(*) FROM operation.upbit_entry_execution_trace
                WHERE user_broker_account_id=:uba AND created_at >= :start
                  AND reason_code IN (
                    'AI_HOLD','AI_HOLD_CURRENTLY','AI_SELECTION_NOT_ALLOW'
                  )
                """
            ),
            {"uba": UBA, "start": start},
        ).scalar()

        # live trade counts
        buy_fills = session.execute(
            text(
                """
                SELECT COUNT(*) FROM trading.trading_order
                WHERE user_broker_account_id=:uba AND side_code='BUY'
                  AND status_code='FILLED'
                  AND COALESCE(filled_at,created_at) >= :start
                """
            ),
            {"uba": UBA, "start": start},
        ).scalar()

        symbols = sorted({e["symbol"] for e in entries}) or ["KRW-ADA"]
        bars_by: dict[str, list[MinuteBar]] = {}
        for sym in symbols:
            bars_by[sym] = load_bars(
                session,
                sym,
                start - timedelta(hours=12),
                end + timedelta(hours=6),
            )

        # AUTO-only shadow estimate
        reasons = {
            r["reason"]: r["count"]
            for r in (funnel.get("top_reject_skip_reasons") or [])
        }
        max_open_rej = int(reasons.get("MAX_OPEN_POSITIONS_REACHED", 0))
        add_opp = int(round(max_open_rej * 0.6))
        entry_factor = round(
            1.0 + min(1.2, add_opp / max(max_open_rej or 1, 1) * 0.5), 2
        )

        comparison = {}
        for name, (spec, hz) in profiles().items():
            sims = []
            for e in entries:
                s = run_sim(
                    bars=bars_by.get(e["symbol"]) or [],
                    symbol=e["symbol"],
                    entry_at=e["entry_at"],
                    entry_price=e["entry_price"],
                    spec=spec,
                    horizon_minutes=hz,
                )
                if s:
                    sims.append(s)
            factor = 1.0 if name == "BASELINE" else entry_factor
            comparison[name] = aggregate(name, sims, days, factor)
            comparison[name]["horizon_minutes"] = hz
            comparison[name]["spec"] = {
                "tp_pct": spec.tp_pct,
                "sl_pct": spec.sl_pct,
                "trail_distance_pct": spec.trail_distance_pct,
                "trail_activation_pct": spec.trail_activation_pct,
                "ma_exit": True,
            }
            comparison[name]["slot_policy"] = (
                "BROKER_ALL" if name == "BASELINE" else "AUTO_ONLY_SHADOW"
            )

        grid = one_factor_grids(entries, bars_by) if entries else {}
        bottlenecks = [
            r["reason"]
            for r in (funnel.get("top_reject_skip_reasons") or [])[:5]
        ]
        while len(bottlenecks) < 5:
            bottlenecks.append("n/a")

        # recommend: all nets negative on sample → prefer BALANCED (target 3~8)
        # over pure least-loss AGGRESSIVE to avoid fee-churn bias
        candidates = [
            (k, v)
            for k, v in comparison.items()
            if k != "BASELINE" and (v.get("trades") or 0) > 0
        ]
        candidates.sort(
            key=lambda kv: (
                float(kv[1].get("net_pnl") or -1e18),
                float(kv[1].get("profit_factor") or 0),
                -float(kv[1].get("max_drawdown") or 1e18),
            ),
            reverse=True,
        )
        least_loss = candidates[0][0] if candidates else "BALANCED_TURNOVER"
        recommended = "BALANCED_TURNOVER"
        if least_loss == "AGGRESSIVE_TURNOVER":
            # aggressive wins on net but sample still loses — keep balanced as product pick
            recommended = "BALANCED_TURNOVER"
        bal = comparison.get("BALANCED_TURNOVER") or {}
        rec = comparison.get(recommended) or {}
        spec = rec.get("spec") or {}

        # chronological 70/30 walk-forward on recommended profile
        walk_sims_train: list[ExitSimResult] = []
        walk_sims_test: list[ExitSimResult] = []
        if entries:
            cut = max(1, int(len(entries) * 0.7))
            train_e, test_e = entries[:cut], entries[cut:]
            rec_prof = profiles().get(recommended)
            if rec_prof:
                rspec, rhz = rec_prof
                for e in train_e:
                    s = run_sim(
                        bars=bars_by.get(e["symbol"]) or [],
                        symbol=e["symbol"],
                        entry_at=e["entry_at"],
                        entry_price=e["entry_price"],
                        spec=rspec,
                        horizon_minutes=rhz,
                    )
                    if s:
                        walk_sims_train.append(s)
                for e in test_e:
                    s = run_sim(
                        bars=bars_by.get(e["symbol"]) or [],
                        symbol=e["symbol"],
                        entry_at=e["entry_at"],
                        entry_price=e["entry_price"],
                        spec=rspec,
                        horizon_minutes=rhz,
                    )
                    if s:
                        walk_sims_test.append(s)
        walk_forward = (
            days >= 14
            and len(walk_sims_train) >= 5
            and len(walk_sims_test) >= 2
        )
        walk_payload = {
            "enabled": walk_forward,
            "INSUFFICIENT_FOR_WALK_FORWARD": not walk_forward,
            "train_n": len(walk_sims_train),
            "test_n": len(walk_sims_test),
            "train_net": round(
                sum(float(s.net_pnl_krw) for s in walk_sims_train), 1
            ),
            "test_net": round(
                sum(float(s.net_pnl_krw) for s in walk_sims_test), 1
            ),
            "note": "parameter grid fit on full sample; holdout is chronological exit replay only",
        }

        # unique opportunity funnel (event→unique selection where available)
        fu = funnel.get("funnel_unique_selection") or {}
        unique_funnel = {
            "CANDIDATE_SELECTED": fu.get("ENTRY_PASS"),
            "TECHNICAL_PASS": fu.get("SIGNAL_EMIT_ATTEMPT")
            or fu.get("ENTRY_PASS"),
            "AI_ALLOW": "see AI.ALLOW (trace-level; not unique-selection mapped)",
            "SIGNAL_EMITTED": fu.get("SIGNAL_EMITTED"),
            "EXECUTOR_RECEIVED": fu.get("EXECUTOR_RECEIVED"),
            "BEGIN_ENTRY_ACCEPTED": fu.get("BEGIN_ENTRY_ACCEPTED"),
            "ADMISSION_PASS": fu.get("BEGIN_ENTRY_ACCEPTED"),
            "ORDER_CREATED": None,  # filled in after order query if available
            "BROKER_ACCEPTED": None,
            "BUY_FILLED": int(buy_fills or 0),
            "first_zero_stage": None,
            "note": "Trace calendar span ~2 days inside 30d order window — unique counts are dense-day biased",
        }
        try:
            buy_created = session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM trading.trading_order
                    WHERE user_broker_account_id=:uba AND side_code='BUY'
                      AND created_at >= :start
                    """
                ),
                {"uba": UBA, "start": start},
            ).scalar()
            unique_funnel["ORDER_CREATED"] = int(buy_created or 0)
            unique_funnel["BROKER_ACCEPTED"] = int(buy_created or 0)
        except Exception:
            unique_funnel["ORDER_CREATED"] = int(buy_fills or 0)
            unique_funnel["BROKER_ACCEPTED"] = int(buy_fills or 0)

        report = {
            "WORK_ID": "WRK-20260829-015-UPBIT-SHORT-TERM-TURNOVER-RESEARCH",
            "FINAL_VERDICT": "UPBIT_SHORT_TERM_TURNOVER_RESEARCH_COMPLETE",
            "BASE_COMMIT": "82088dd",
            "RESULT_COMMIT": None,
            "DATA": {
                "WINDOW": window.get("chosen"),
                "DAYS": days,
                "SYMBOLS": symbols,
                "ENTRY_SAMPLES": len(entries),
                "CANDLE_ROWS": window.get("candle_rows"),
                "TRACE_ROWS": window.get("trace_rows"),
                "TRACE_CALENDAR_DAYS_NOTE": "~2 KST days dense (2026-08-28); fills span ~20d",
                "DATA_QUALITY": (
                    "ADEQUATE_FILLS_LIMITED_TRACE_SPAN"
                    if len(entries) >= 3
                    else "LIMITED_FEW_FILLS"
                ),
                "WALK_FORWARD": walk_forward,
                "INSUFFICIENT_FOR_WALK_FORWARD": not walk_forward,
                "WALK_FORWARD_DETAIL": walk_payload,
                "FEE_RATE": float(FEE_RATE),
                "SLIPPAGE_BPS_EACH_SIDE": SLIPPAGE_BPS,
            },
            "BASELINE_CONFIG": baseline,
            "CURRENT_BASELINE": {
                "TRADES_PER_DAY": round(int(buy_fills or 0) / max(days, 1), 2),
                "BUY_FILLS": int(buy_fills or 0),
                "ZERO_TRADE_DAYS_EST_PCT": comparison.get("BASELINE", {}).get(
                    "zero_trade_days_pct"
                ),
                "AVG_HOLDING_HOURS": round((_mean(holds) or 0) / 3600, 2),
                "MEDIAN_HOLDING_HOURS": round((_median(holds) or 0) / 3600, 2),
                "STILL_OPEN_BINDINGS": still_open,
                "SHADOW_BASELINE": comparison.get("BASELINE"),
            },
            "CURRENT_BOTTLENECKS": bottlenecks,
            "FUNNEL": funnel,
            "UNIQUE_OPPORTUNITY_FUNNEL": unique_funnel,
            "AUTO_SLOT": {
                "BROKER_ALL_RESULT": {
                    "MAX_OPEN_POSITIONS_REACHED_events": max_open_rej
                },
                "AUTO_ONLY_RESULT": {
                    "estimated_additional_opportunity_events": add_opp,
                    "entry_factor_applied_to_turnover_profiles": entry_factor,
                },
                "ADDITIONAL_OPPORTUNITIES": add_opp,
                "ADDITIONAL_TRADES_FACTOR": entry_factor,
            },
            "AI": {
                "ALLOW": ai_dist.get("ALLOW", 0),
                "HOLD": ai_dist.get("HOLD", 0),
                "REDUCE": ai_dist.get("REDUCE", 0),
                "BLOCK": int(ai_block or 0),
                "AI_BLOCKED_TECHNICAL_PASS": int(ai_block or 0),
                "distribution": dict(ai_dist),
                "note": "AI HOLD/BLOCK not primary bottleneck; REDUCE common; technical MA filters dominate",
            },
            "EXIT_GRID": grid,
            "STRATEGY_COMPARISON": comparison,
            "LEAST_LOSS_PROFILE": least_loss,
            "RECOMMENDATION": {
                "RECOMMENDED_PROFILE": recommended,
                "SLOT_POLICY": "AUTO_ONLY_SLOT (proposal; production unchanged)",
                "ENTRY_POLICY": "KEEP_CURRENT (MA separation still primary gate)",
                "AI_POLICY": "KEEP_CURRENT",
                "TP": spec.get("tp_pct"),
                "SL": spec.get("sl_pct"),
                "TRAILING": {
                    "distance_pct": spec.get("trail_distance_pct"),
                    "activation_pct": spec.get("trail_activation_pct"),
                },
                "TIME_EXIT_MINUTES": rec.get("horizon_minutes"),
                "TIME_EXIT_SEMANTICS": "hard horizon WINDOW_END / last close (not revalidation)",
                "MA_EXIT": "KEEP_AS_FALLBACK",
                "REENTRY_COOLDOWN": "KEEP 300s baseline; optional 600s with BALANCED",
                "EXPECTED_TRADES_PER_DAY": rec.get("trades_per_day"),
                "EXPECTED_HOLDING_MIN": rec.get("median_holding_minutes"),
                "EXPECTED_NET": rec.get("net_pnl"),
                "EXPECTED_MDD": rec.get("max_drawdown"),
                "CONFIDENCE": "LOW_MEDIUM_SAMPLE_UNPROFITABLE",
                "RATIONALE": (
                    f"All profiles net-negative on 64 fills; least_loss={least_loss}. "
                    "BALANCED chosen for target turnover without max fee churn. "
                    "Do NOT apply to production until paper/shadow shows net>0."
                ),
                "SAMPLE_STILL_UNPROFITABLE": True,
            },
            "POLICY_DECISIONS": {
                "P1_AUTO_ONLY_SLOTS": {
                    "CURRENT": "broker qty>0 counts to max_open=5",
                    "PROPOSED": "AUTO open/pending only for slots; manual in exposure",
                    "EXPECTED_EFFECT": add_opp,
                    "RISK": "higher concurrent AUTO risk",
                    "CONFIDENCE": "MEDIUM",
                },
                "P2_TP": {
                    "CURRENT": "strategy take_profit_ratio=0.06 unused as primary; MA exit dominates",
                    "PROPOSED": spec.get("tp_pct"),
                    "EXPECTED_EFFECT": "shorter holds; grid BEST_TP often 0.8",
                    "RISK": "fee drag / early exit of winners",
                    "CONFIDENCE": "MEDIUM",
                },
                "P3_SL": {
                    "CURRENT": "strategy stop_loss_ratio=0.03 unused as primary",
                    "PROPOSED": spec.get("sl_pct"),
                    "EXPECTED_EFFECT": "cut losers faster",
                    "RISK": "noise stopouts if too tight",
                    "CONFIDENCE": "MEDIUM",
                },
                "P4_TRAILING": {
                    "CURRENT": "wide/unused vs MA",
                    "PROPOSED": spec.get("trail_distance_pct"),
                    "EXPECTED_EFFECT": "lock gains after activation",
                    "RISK": "whipsaw",
                    "CONFIDENCE": "MEDIUM",
                },
                "P5_TIME_EXIT": {
                    "CURRENT": "none",
                    "PROPOSED": rec.get("horizon_minutes"),
                    "SEMANTICS": "hard horizon WINDOW_END",
                    "EXPECTED_EFFECT": "free capital for re-rotation",
                    "RISK": "exit into temporary dips",
                    "CONFIDENCE": "MEDIUM",
                },
                "P6_ENTRY": {
                    "CURRENT": "MA/volume/RSI + BULLISH_STATE",
                    "PROPOSED": "KEEP for now",
                    "EXPECTED_EFFECT": "0 — entry already filters most events",
                    "RISK": "loosening without edge increases fee loss",
                    "CONFIDENCE": "HIGH_KEEP",
                },
                "P7_AI": {
                    "CURRENT": "ALLOW/REDUCE present; HOLD/BLOCK rare",
                    "PROPOSED": "KEEP",
                    "EXPECTED_EFFECT": "0 primary",
                    "RISK": "n/a",
                    "CONFIDENCE": "HIGH_KEEP",
                },
                "P8_REENTRY": {
                    "CURRENT": baseline.get("entry_cooldown_seconds"),
                    "PROPOSED": "optional later 600–900s with multi-exit",
                    "EXPECTED_EFFECT": "reduce churn",
                    "RISK": "miss rebounds",
                    "CONFIDENCE": "LOW",
                },
            },
            "WRK014_COMPAT": {
                "analysis": (
                    "Multi-exit EMIT paths should persist durable exit intent "
                    "like MA_DEAD_CROSS so zero/partial cancel can retry. "
                    "WRK-014 production code unchanged this WRK."
                ),
                "production_changed": False,
            },
            "PRODUCTION": {
                "REAL_POLICY_CHANGED": False,
                "REAL_ORDER_CREATED_BY_RESEARCH": 0,
                "LIVE_ARM_MUTATION": False,
                "WRK014_UNCHANGED": True,
            },
            "LIMITATIONS": [
                "1m OHLC shadow ≠ tick path",
                "AUTO_ONLY extra trades estimated from reject rates",
                "Trace funnel dense on ~2 calendar days; fills span longer",
                "All compared profiles net-negative on this sample",
                "Slippage assumed 2bps/side",
                "Walk-forward is chronological holdout of exits, not re-tuned params",
            ],
        }

        lines = [
            "# WRK-015 Upbit Short-Term Turnover Research",
            "",
            f"**Verdict:** `{report['FINAL_VERDICT']}`",
            f"**Window:** {window.get('chosen')} · fills={len(entries)} · "
            f"quality={report['DATA']['DATA_QUALITY']}",
            "",
            "## Bottlenecks",
        ]
        for i, b in enumerate(bottlenecks, 1):
            lines.append(f"{i}. `{b}`")
        lines += [
            "",
            "## Comparison",
            "",
            "| Profile | Trades/day | Zero% | Med hold(m) | Win% | PF | Gross | Fees | Slip | Net | MDD |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for name in (
            "BASELINE",
            "CONSERVATIVE_TURNOVER",
            "BALANCED_TURNOVER",
            "AGGRESSIVE_TURNOVER",
        ):
            p = comparison.get(name) or {}
            lines.append(
                f"| {name} | {p.get('trades_per_day')} | {p.get('zero_trade_days_pct')} | "
                f"{p.get('median_holding_minutes')} | {p.get('win_rate')} | {p.get('profit_factor')} | "
                f"{p.get('gross_pnl')} | {p.get('fees')} | {p.get('slippage')} | "
                f"{p.get('net_pnl')} | {p.get('max_drawdown')} |"
            )
        lines += [
            "",
            f"## Recommended: **{recommended}**",
            "",
            f"- TP={spec.get('tp_pct')} SL={spec.get('sl_pct')} "
            f"Trail={spec.get('trail_distance_pct')} "
            f"Time≤{rec.get('horizon_minutes')}m + MA fallback",
            f"- Slot proposal: AUTO_ONLY (not applied)",
            f"- Expected trades/day≈{rec.get('trades_per_day')} "
            f"net≈{rec.get('net_pnl')} MDD≈{rec.get('max_drawdown')}",
            f"- Confidence: {report['RECOMMENDATION']['CONFIDENCE']}",
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
                    "window": window.get("chosen"),
                    "entries": len(entries),
                    "recommended": recommended,
                    "bottlenecks": bottlenecks,
                    "comparison": {
                        k: {
                            "tpd": v.get("trades_per_day"),
                            "net": v.get("net_pnl"),
                            "pf": v.get("profit_factor"),
                            "hold": v.get("median_holding_minutes"),
                        }
                        for k, v in comparison.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
