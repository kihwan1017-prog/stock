"""UBA1380 35RT exit/churn shadow replay — research only, REAL mutation 없음."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import select

from stock_platform.broker.fee_policy import UpbitFeePolicy
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.markets.models import CandleMinute, Instrument
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    MinuteBar,
    as_utc,
    bars_from_rows,
    floor_minute,
    return_pct,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_policy_ab import (
    MA_LONG,
    MA_SHORT,
    ExitPolicySpec,
    _arm_kpis,
    _fee_bundle,
    _sma,
    simulate_exit_policy,
)
from stock_platform.realtime.ma_exit_policy import (
    is_dead_cross_confirmed,
    is_min_holding_satisfied,
    is_protective_exit_reason,
)

EARLY_DUMP_SECONDS = 300
FEE_RT_PCT = 0.10
MA_EVAL_MINUTES = 1  # 1m bar = 1 evaluation (portfolio realtime path)


@dataclass(frozen=True, slots=True)
class FrozenRoundTrip:
    trade_id: int
    symbol: str
    entry_time: datetime
    entry_price: Decimal
    quantity: Decimal
    buy_amount: Decimal
    buy_fee: Decimal
    sell_fee: Decimal
    actual_exit_time: datetime
    actual_exit_price: Decimal
    actual_exit_reason: str
    actual_gross_pnl: float
    actual_total_fee: float
    actual_net_pnl: float
    path_insufficient: bool = False
    kst_close_date: str | None = None


@dataclass(frozen=True, slots=True)
class ReplayMaSpec:
    """Exit-only replay spec (entry 고정)."""

    label: str
    group: str  # E0|E1|E2|...
    exit_min_ma_separation_pct: float = 0.03
    ma_exit_min_holding_seconds: int = 180
    tp_pct: float = 10.0
    sl_pct: float = 5.0
    trail_distance_pct: float = 3.0
    trail_activation_pct: float | None = None
    confirm_evaluations: int = 1
    confirm_delay_seconds: int = 0
    pnl_aware_ma: bool = False
    entry_ma_sep_min_pct: float | None = None  # E4/E6 entry skip
    entry_momentum_min_pct: float | None = None  # E6: 1m momentum
    cooldown_minutes: int | None = None  # E5 — entry filter across timeline


def frozen_from_audit_row(row: dict[str, Any]) -> FrozenRoundTrip:
    entry_at = datetime.fromisoformat(row["buy_time_kst"])
    exit_at = datetime.fromisoformat(row["sell_time_kst"])
    path = row.get("path") or {}
    return FrozenRoundTrip(
        trade_id=int(row["binding_id"]),
        symbol=str(row["symbol"]),
        entry_time=entry_at,
        entry_price=Decimal(str(row["buy_price"])),
        quantity=Decimal(str(row["quantity"])),
        buy_amount=Decimal(str(row["buy_amount"])),
        buy_fee=Decimal(str(row["buy_fee"])),
        sell_fee=Decimal(str(row["sell_fee"])),
        actual_exit_time=exit_at,
        actual_exit_price=Decimal(str(row["sell_price"])),
        actual_exit_reason=str(row.get("exit_reason") or "UNKNOWN"),
        actual_gross_pnl=float(row["gross_pnl"]),
        actual_total_fee=float(row["total_fee"]),
        actual_net_pnl=float(row["net_pnl"]),
        path_insufficient=bool(path.get("insufficient")),
        kst_close_date=row.get("kst_close_date"),
    )


def load_frozen_dataset(audit_path: Path) -> list[FrozenRoundTrip]:
    data = json.loads(audit_path.read_text(encoding="utf-8"))
    return [frozen_from_audit_row(r) for r in data["ROUND_TRIPS"]]


def fetch_minute_bars(
    session,
    *,
    symbol: str,
    start: datetime,
    end: datetime,
) -> list[MinuteBar]:
    stmt = (
        select(CandleMinute)
        .join(Instrument, Instrument.instrument_id == CandleMinute.instrument_id)
        .where(
            Instrument.exchange_code == "UPBIT",
            Instrument.symbol == symbol.upper(),
            CandleMinute.timeframe == 1,
            CandleMinute.candle_at >= as_utc(start),
            CandleMinute.candle_at <= as_utc(end),
        )
        .order_by(CandleMinute.candle_at.asc())
    )
    return bars_from_rows(list(session.scalars(stmt)))


def e0_kpis(trips: Sequence[FrozenRoundTrip]) -> dict[str, Any]:
    rows = [
        {
            "net_pnl_krw": t.actual_net_pnl,
            "gross_pnl_krw": t.actual_gross_pnl,
            "estimated_fee_krw": t.actual_total_fee,
            "holding_seconds": (
                as_utc(t.actual_exit_time) - as_utc(t.entry_time)
            ).total_seconds(),
            "exit_reason": t.actual_exit_reason,
            "fee_only_loss": abs(t.actual_gross_pnl) < 1e-6 and t.actual_net_pnl < 0,
        }
        for t in trips
    ]
    k = _arm_kpis(rows)
    k["expectancy"] = round(k["net_pnl"] / k["sample_count"], 4) if k["sample_count"] else None
    k["early_dump_count"] = sum(
        1
        for t in trips
        if "MA_DEAD" in t.actual_exit_reason.upper()
        and (as_utc(t.actual_exit_time) - as_utc(t.entry_time)).total_seconds()
        < EARLY_DUMP_SECONDS
    )
    k["fee_churn_count"] = sum(
        1
        for t in trips
        if abs(t.actual_gross_pnl) < 1e-6 and t.actual_net_pnl < -1e-6
    )
    return k


def _baseline_spec_from_settings() -> ExitPolicySpec:
    s = get_settings()
    return ExitPolicySpec(
        label="SIM_BASELINE",
        tp_pct=float(s.position_exit_take_profit_ratio) * 100,
        sl_pct=float(s.position_exit_stop_loss_ratio) * 100,
        trail_distance_pct=float(s.position_exit_trailing_stop_ratio or 0.03) * 100,
        trail_activation_pct=None,
        ma_exit_enabled=True,
        exit_min_ma_separation_pct=float(s.upbit_portfolio_exit_min_ma_separation_pct),
        ma_exit_min_holding_seconds=int(s.upbit_portfolio_ma_exit_min_holding_seconds),
    )


def simulate_ma_exit_replay(
    bars: Sequence[MinuteBar],
    trip: FrozenRoundTrip,
    spec: ReplayMaSpec,
    *,
    now: datetime | None = None,
    horizon_minutes: int | None = None,
) -> dict[str, Any]:
    """1m OHLC replay — SL/TP/TRAIL 우선, MA variant."""

    entry = trip.entry_price
    t0 = as_utc(trip.entry_time)
    actual_end = as_utc(trip.actual_exit_time)
    hold_min = max(
        60,
        int((actual_end - t0).total_seconds() / 60) + 90,
    )
    horizon = horizon_minutes or hold_min
    now_utc = as_utc(now or actual_end + timedelta(minutes=30))
    horizon_end = t0 + timedelta(minutes=horizon)
    rate = UpbitFeePolicy.DEFAULT_TAKER_RATE
    notional = trip.buy_amount

    tp_price = entry * (Decimal("1") + Decimal(str(spec.tp_pct)) / Decimal("100"))
    sl_price = entry * (Decimal("1") - Decimal(str(spec.sl_pct)) / Decimal("100"))
    trail_frac = Decimal(str(spec.trail_distance_pct)) / Decimal("100")

    ordered = sorted(
        (
            b
            for b in bars
            if b.is_completed(now=now_utc, timeframe_minutes=1)
            and as_utc(b.candle_at) <= now_utc
            and as_utc(b.candle_at) <= horizon_end
        ),
        key=lambda b: as_utc(b.candle_at),
    )
    closes: list[Decimal] = [b.close for b in ordered]
    start_floor = floor_minute(t0)

    high_water = entry
    trail_active = False
    exit_reason = "WINDOW_END"
    exit_at: datetime | None = None
    exit_price: Decimal | None = None

    confirm_streak = 0
    first_cross_at: datetime | None = None

    for idx, bar in enumerate(ordered):
        at = as_utc(bar.candle_at)
        if at < start_floor:
            continue

        if bar.high > high_water:
            high_water = bar.high
        if high_water > entry:
            trail_active = True
        trail_trigger = high_water * (Decimal("1") - trail_frac)

        # 보호 청산 — confirmation/delay 무시
        if bar.low <= sl_price:
            exit_reason = "STOP_LOSS"
            exit_at = at
            exit_price = sl_price
            break
        if bar.high >= tp_price:
            exit_reason = "TAKE_PROFIT"
            exit_at = at
            exit_price = tp_price
            break
        if trail_active and bar.low <= trail_trigger:
            exit_reason = "TRAILING_STOP"
            exit_at = at
            exit_price = trail_trigger
            break

        short_ma = _sma(closes, idx, MA_SHORT)
        long_ma = _sma(closes, idx, MA_LONG)
        prev_s = _sma(closes, idx - 1, MA_SHORT) if idx > 0 else None
        prev_l = _sma(closes, idx - 1, MA_LONG) if idx > 0 else None
        raw_dead = (
            prev_s is not None
            and prev_l is not None
            and short_ma is not None
            and long_ma is not None
            and prev_s >= prev_l
            and short_ma < long_ma
        )
        hold_ok = is_min_holding_satisfied(
            opened_at=t0,
            min_holding_seconds=int(spec.ma_exit_min_holding_seconds),
            now=at + timedelta(minutes=1),
        )
        sep_ok = is_dead_cross_confirmed(
            short_ma=short_ma,
            long_ma=long_ma,
            exit_min_ma_separation_pct=spec.exit_min_ma_separation_pct,
        )

        if raw_dead and sep_ok and hold_ok:
            if first_cross_at is None:
                first_cross_at = at
            confirm_streak += 1
        elif short_ma is not None and long_ma is not None and short_ma >= long_ma:
            confirm_streak = 0
            first_cross_at = None

        if not (raw_dead and sep_ok and hold_ok):
            continue

        delay_ok = True
        if spec.confirm_delay_seconds > 0 and first_cross_at is not None:
            delay_ok = (at - first_cross_at).total_seconds() >= spec.confirm_delay_seconds

        eval_ok = confirm_streak >= int(spec.confirm_evaluations)

        if spec.pnl_aware_ma:
            fees = _fee_bundle(
                entry=entry,
                exit_price=bar.close,
                notional=notional,
                fee_rate=rate,
            )
            net_pct = fees["net_return_pct"]
            if net_pct < -1.0:
                eval_ok = True
                delay_ok = True
            elif abs(net_pct) < 0.15:
                eval_ok = confirm_streak >= int(spec.confirm_evaluations) + 1
            elif net_pct > 0.3:
                eval_ok = confirm_streak >= int(spec.confirm_evaluations)

        if eval_ok and delay_ok:
            exit_reason = "MA_DEAD_CROSS"
            exit_at = at
            exit_price = bar.close
            break

    if exit_price is None and ordered:
        post = [b for b in ordered if as_utc(b.candle_at) >= start_floor]
        if post:
            last = post[-1]
            exit_at = as_utc(last.candle_at)
            exit_price = last.close
            exit_reason = "WINDOW_END"

    if exit_price is None:
        return {
            "trade_id": trip.trade_id,
            "skipped": False,
            "exit_reason": "NO_BARS",
            "net_pnl_krw": 0.0,
            "path_insufficient": True,
        }

    fees = _fee_bundle(
        entry=entry,
        exit_price=Decimal(str(exit_price)),
        notional=notional,
        fee_rate=rate,
    )
    hold = (as_utc(exit_at) - t0).total_seconds() if exit_at else None
    fee_only = fees["gross_pnl"] >= -1e-9 and fees["net_pnl"] < 0
    return {
        "trade_id": trip.trade_id,
        "symbol": trip.symbol,
        "skipped": False,
        "exit_reason": exit_reason,
        "exit_at": as_utc(exit_at).isoformat() if exit_at else None,
        "exit_price": float(exit_price),
        "holding_seconds": hold,
        "gross_pnl_krw": fees["gross_pnl"],
        "estimated_fee_krw": fees["fee_total"],
        "net_pnl_krw": fees["net_pnl"],
        "net_return_pct": fees["net_return_pct"],
        "fee_only_loss": fee_only,
        "protective_exit": is_protective_exit_reason(exit_reason),
        "path_insufficient": False,
    }


def _entry_skip_at_open(
    bars: Sequence[MinuteBar],
    trip: FrozenRoundTrip,
    spec: ReplayMaSpec,
) -> tuple[bool, str | None]:
    """Entry 시점에만 사용 가능한 feature — lookahead 금지."""

    t0 = floor_minute(as_utc(trip.entry_time))
    ordered = sorted(bars, key=lambda b: as_utc(b.candle_at))
    idx = next(
        (i for i, b in enumerate(ordered) if as_utc(b.candle_at) >= t0),
        None,
    )
    if idx is None or idx < MA_LONG:
        return False, None
    closes = [b.close for b in ordered[: idx + 1]]
    short_ma = _sma(closes, idx, MA_SHORT)
    long_ma = _sma(closes, idx, MA_LONG)
    if spec.entry_ma_sep_min_pct is not None and short_ma and long_ma and long_ma > 0:
        sep = float((short_ma - long_ma) / long_ma * Decimal("100"))
        need = float(spec.entry_ma_sep_min_pct) + FEE_RT_PCT
        if sep < need:
            return True, f"MA_SEP<{need:.3f}%"
    if spec.entry_momentum_min_pct is not None and idx >= 1:
        prev = closes[idx - 1]
        cur = closes[idx]
        if prev > 0:
            mom = float((cur - prev) / prev * Decimal("100"))
            if mom < float(spec.entry_momentum_min_pct):
                return True, f"MOMENTUM<{spec.entry_momentum_min_pct}%"
    return False, None


def apply_cooldown_skips(
    trips: Sequence[FrozenRoundTrip],
    cooldown_minutes: int,
) -> set[int]:
    """동일 symbol 재진입 shadow skip (trade_id set)."""

    skipped: set[int] = set()
    last_exit: dict[str, datetime] = {}
    for trip in sorted(trips, key=lambda t: as_utc(t.entry_time)):
        sym = trip.symbol
        prev = last_exit.get(sym)
        if prev is not None:
            gap = (as_utc(trip.entry_time) - prev).total_seconds()
            if gap < cooldown_minutes * 60:
                skipped.add(trip.trade_id)
        if trip.trade_id not in skipped:
            last_exit[sym] = as_utc(trip.actual_exit_time)
    return skipped


def run_experiment(
    trips: Sequence[FrozenRoundTrip],
    bars_by_symbol: dict[str, list[MinuteBar]],
    spec: ReplayMaSpec,
) -> dict[str, Any]:
    cooldown_skipped: set[int] = set()
    if spec.cooldown_minutes:
        cooldown_skipped = apply_cooldown_skips(trips, spec.cooldown_minutes)

    results: list[dict[str, Any]] = []
    skipped_entries = 0
    for trip in trips:
        if trip.trade_id in cooldown_skipped:
            skipped_entries += 1
            continue
        bars = bars_by_symbol.get(trip.symbol, [])
        if spec.entry_ma_sep_min_pct is not None or spec.entry_momentum_min_pct is not None:
            skip, reason = _entry_skip_at_open(bars, trip, spec)
            if skip:
                skipped_entries += 1
                results.append(
                    {
                        "trade_id": trip.trade_id,
                        "skipped": True,
                        "skip_reason": reason,
                        "net_pnl_krw": 0.0,
                    }
                )
                continue
        if len(bars) < MA_LONG + 5:
            results.append(
                {
                    "trade_id": trip.trade_id,
                    "skipped": False,
                    "path_insufficient": True,
                    "net_pnl_krw": trip.actual_net_pnl,
                    "note": "PATH_INSUFFICIENT_USED_ACTUAL",
                }
            )
            continue
        results.append(simulate_ma_exit_replay(bars, trip, spec))

    active = [r for r in results if not r.get("skipped") and not r.get("path_insufficient")]
    kpi = _arm_kpis(active)
    kpi["expectancy"] = (
        round(kpi["net_pnl"] / kpi["sample_count"], 4) if kpi["sample_count"] else None
    )
    kpi["early_dump_count"] = sum(
        1
        for r in active
        if r.get("exit_reason") == "MA_DEAD_CROSS"
        and (r.get("holding_seconds") or 99999) < EARLY_DUMP_SECONDS
    )
    kpi["fee_churn_count"] = sum(1 for r in active if r.get("fee_only_loss"))
    kpi["skipped_entries"] = skipped_entries
    kpi["path_insufficient_count"] = sum(
        1 for r in results if r.get("path_insufficient")
    )
    return {
        "id": spec.label,
        "group": spec.group,
        "rule": spec.label,
        "kpis": kpi,
        "results": results,
    }


def diff_vs_e0(e0: dict[str, Any], exp: dict[str, Any]) -> dict[str, Any]:
    k = exp["kpis"]
    net_benefit = round(k["net_pnl"] - e0["net_pnl"], 4)
    return {
        "net_benefit_vs_e0": net_benefit,
        "loss_avoided": round(max(0, e0["net_pnl"] - k["net_pnl"]), 4) if net_benefit > 0 else 0,
        "win_missed_estimate": round(max(0, k["net_pnl"] - e0["net_pnl"]), 4) if net_benefit < 0 else 0,
        "fees_saved": round(e0["fees"] - k["fees"], 4),
        "early_dump_reduction": e0.get("early_dump_count", 0) - k.get("early_dump_count", 0),
        "trade_reduction": e0["sample_count"] - k["sample_count"],
    }


def build_experiment_specs() -> list[ReplayMaSpec]:
    base = _baseline_spec_from_settings()
    specs: list[ReplayMaSpec] = [
        ReplayMaSpec(
            label="E0_ACTUAL",
            group="E0",
        ),
        ReplayMaSpec(
            label="SIM_E0_POLICY",
            group="E0",
            exit_min_ma_separation_pct=base.exit_min_ma_separation_pct,
            ma_exit_min_holding_seconds=base.ma_exit_min_holding_seconds,
            tp_pct=base.tp_pct,
            sl_pct=base.sl_pct,
            trail_distance_pct=base.trail_distance_pct,
        ),
        ReplayMaSpec(label="E1A_confirm2", group="E1", confirm_evaluations=2),
        ReplayMaSpec(label="E1B_confirm3", group="E1", confirm_evaluations=3),
        ReplayMaSpec(label="E1C_delay30s", group="E1", confirm_delay_seconds=30),
        ReplayMaSpec(label="E1D_delay60s", group="E1", confirm_delay_seconds=60),
        ReplayMaSpec(label="E2_sep0.05", group="E2", exit_min_ma_separation_pct=0.05),
        ReplayMaSpec(label="E2_sep0.10", group="E2", exit_min_ma_separation_pct=0.10),
        ReplayMaSpec(label="E2_sep0.15", group="E2", exit_min_ma_separation_pct=0.15),
        ReplayMaSpec(label="E2_sep0.20", group="E2", exit_min_ma_separation_pct=0.20),
        ReplayMaSpec(label="E2_sep0.30", group="E2", exit_min_ma_separation_pct=0.30),
        ReplayMaSpec(label="E3_pnl_aware", group="E3", pnl_aware_ma=True, confirm_evaluations=2),
        ReplayMaSpec(label="E4_fee_buf0.05", group="E4", entry_ma_sep_min_pct=0.05),
        ReplayMaSpec(label="E4_fee_buf0.10", group="E4", entry_ma_sep_min_pct=0.10),
        ReplayMaSpec(label="E4_fee_buf0.15", group="E4", entry_ma_sep_min_pct=0.15),
        ReplayMaSpec(label="E4_fee_buf0.20", group="E4", entry_ma_sep_min_pct=0.20),
        ReplayMaSpec(label="E5_cd5m", group="E5", cooldown_minutes=5),
        ReplayMaSpec(label="E5_cd10m", group="E5", cooldown_minutes=10),
        ReplayMaSpec(label="E5_cd15m", group="E5", cooldown_minutes=15),
        ReplayMaSpec(label="E5_cd30m", group="E5", cooldown_minutes=30),
        ReplayMaSpec(label="E6_mom0.05", group="E6", entry_momentum_min_pct=0.05),
        ReplayMaSpec(label="E6_mom0.10", group="E6", entry_momentum_min_pct=0.10),
        ReplayMaSpec(
            label="C1_confirm2_fee0.10",
            group="E7",
            confirm_evaluations=2,
            entry_ma_sep_min_pct=0.10,
        ),
        ReplayMaSpec(
            label="C2_sep0.15_cd10m",
            group="E7",
            exit_min_ma_separation_pct=0.15,
            cooldown_minutes=10,
        ),
        ReplayMaSpec(
            label="C3_confirm2_fee_cd10",
            group="E7",
            confirm_evaluations=2,
            entry_ma_sep_min_pct=0.10,
            cooldown_minutes=10,
        ),
        ReplayMaSpec(
            label="C4_confirm2_sep0.15",
            group="E7",
            confirm_evaluations=2,
            exit_min_ma_separation_pct=0.15,
        ),
        ReplayMaSpec(
            label="C5_conservative",
            group="E7",
            confirm_evaluations=3,
            exit_min_ma_separation_pct=0.15,
            entry_ma_sep_min_pct=0.10,
            cooldown_minutes=15,
        ),
    ]
    return specs


def split_train_valid(trips: Sequence[FrozenRoundTrip]) -> tuple[list[FrozenRoundTrip], list[FrozenRoundTrip]]:
    ordered = sorted(trips, key=lambda t: as_utc(t.entry_time))
    cut = int(len(ordered) * 0.6)
    return ordered[:cut], ordered[cut:]


def run_full_replay(audit_path: Path) -> dict[str, Any]:
    trips = load_frozen_dataset(audit_path)
    e0 = e0_kpis(trips)

    factory = get_session_factory()
    bars_by_symbol: dict[str, list[MinuteBar]] = {}
    with factory() as session:
        for sym in {t.symbol for t in trips}:
            t_min = min(as_utc(t.entry_time) for t in trips if t.symbol == sym)
            t_max = max(as_utc(t.actual_exit_time) for t in trips if t.symbol == sym)
            warmup = t_min - timedelta(minutes=MA_LONG + 30)
            end = t_max + timedelta(minutes=120)
            bars_by_symbol[sym] = fetch_minute_bars(
                session, symbol=sym, start=warmup, end=end
            )

    specs = build_experiment_specs()
    experiments: list[dict[str, Any]] = []
    for spec in specs:
        if spec.label == "E0_ACTUAL":
            experiments.append(
                {
                    "id": spec.label,
                    "group": spec.group,
                    "rule": "actual_fills",
                    "kpis": {**e0, "skipped_entries": 0},
                    "results": [],
                }
            )
            continue
        if spec.label == "SIM_E0_POLICY":
            base = _baseline_spec_from_settings()
            sim_results = []
            for trip in trips:
                bars = bars_by_symbol.get(trip.symbol, [])
                if len(bars) < MA_LONG + 5:
                    continue
                r = simulate_exit_policy(
                    bars,
                    symbol=trip.symbol,
                    entry_at=trip.entry_time,
                    entry_price=trip.entry_price,
                    spec=base,
                    now=as_utc(trip.actual_exit_time) + timedelta(minutes=60),
                    horizon_minutes=max(
                        60,
                        int(
                            (
                                as_utc(trip.actual_exit_time) - as_utc(trip.entry_time)
                            ).total_seconds()
                            / 60
                        )
                        + 60,
                    ),
                    notional_krw=trip.buy_amount,
                )
                sim_results.append(r.to_dict())
            experiments.append(
                {
                    "id": spec.label,
                    "group": spec.group,
                    "rule": "simulate_exit_policy baseline",
                    "kpis": _arm_kpis(sim_results),
                    "results": sim_results,
                    "e0_match_note": "SIM may differ from ACTUAL fills",
                }
            )
            continue
        exp = run_experiment(trips, bars_by_symbol, spec)
        exp["diff_vs_e0"] = diff_vs_e0(e0, exp)
        experiments.append(exp)

    exit_only_exps = [e for e in experiments if e["group"] in {"E1", "E2", "E3"}]
    entry_exps = [e for e in experiments if e["group"] in {"E4", "E5", "E6"}]
    combined_exps = [e for e in experiments if e["group"] == "E7"]

    def _best(candidates: list[dict], key: str = "net_benefit_vs_e0") -> dict | None:
        scored = [c for c in candidates if c.get("diff_vs_e0")]
        if not scored:
            return None
        return max(scored, key=lambda x: x["diff_vs_e0"].get(key, -999999))

    best_exit = _best(exit_only_exps)
    best_entry = _best(entry_exps)
    best_combined = _best(combined_exps)

    train, valid = split_train_valid(trips)
    robustness: dict[str, Any] = {}
    if len(valid) >= 5:
        e0_train = e0_kpis(train)
        e0_valid = e0_kpis(valid)
        robustness = {
            "train_n": len(train),
            "valid_n": len(valid),
            "e0_train_net": e0_train["net_pnl"],
            "e0_valid_net": e0_valid["net_pnl"],
        }
        if best_exit:
            spec_map = {s.label: s for s in specs}
            bs = spec_map.get(best_exit["id"])
            if bs:
                tr = run_experiment(train, bars_by_symbol, bs)
                va = run_experiment(valid, bars_by_symbol, bs)
                robustness["best_exit_train_net"] = tr["kpis"]["net_pnl"]
                robustness["best_exit_valid_net"] = va["kpis"]["net_pnl"]
                robustness["best_exit_valid_benefit"] = diff_vs_e0(e0_valid, va)
                robustness["best_exit_id"] = best_exit["id"]

    # fragility: exclude top loss symbols
    top_loss_syms = {"KRW-PUNDIX", "KRW-SUI"}
    excl = [t for t in trips if t.symbol not in top_loss_syms]
    fragility = {
        "exclude_symbols": sorted(top_loss_syms),
        "e0_net_excluded": e0_kpis(excl)["net_pnl"] if excl else None,
        "fragile_if_large_swing": abs(e0["net_pnl"] - e0_kpis(excl)["net_pnl"]) > 200,
    }

    premature = [
        t
        for t in trips
        if (t.path_insufficient is False)
        and (t.actual_net_pnl < 0)
        and ((t.actual_exit_time - t.entry_time).total_seconds() < 3600)
    ]

    return {
        "schema": "upbit_exit_churn_shadow_replay_v1",
        "FINAL_VERDICT": "UPBIT_EXIT_CHURN_SHADOW_REPLAY_COMPLETE",
        "dataset_frozen_n": len(trips),
        "BASELINE_E0": e0,
        "E0_EQUALITY_CHECK": {
            "expected_net": round(sum(t.actual_net_pnl for t in trips), 4),
            "kpi_net": e0["net_pnl"],
            "match": abs(round(sum(t.actual_net_pnl for t in trips), 4) - e0["net_pnl"]) < 0.01,
        },
        "SLIPPAGE_MODELED": "SLIPPAGE_NOT_MODELED",
        "experiments": experiments,
        "BEST_EXIT_SHADOW": best_exit["id"] if best_exit else None,
        "BEST_EXIT_NET_BENEFIT": best_exit["diff_vs_e0"]["net_benefit_vs_e0"] if best_exit else None,
        "BEST_EXIT_NOTES": (
            "Exit-only E1/E2/E3; no entry skip"
            if best_exit
            else None
        ),
        "BEST_ENTRY_SHADOW": best_entry["id"] if best_entry else None,
        "BEST_ENTRY_NET_BENEFIT": best_entry["diff_vs_e0"]["net_benefit_vs_e0"] if best_entry else None,
        "BEST_ENTRY_TRADE_REDUCTION_WARNING": (
            best_entry["diff_vs_e0"].get("trade_reduction", 0) > 10 if best_entry else False
        ),
        "BEST_COMBINED_SHADOW": best_combined["id"] if best_combined else None,
        "BEST_COMBINED_NET": best_combined["kpis"]["net_pnl"] if best_combined else None,
        "BEST_COMBINED_PF": best_combined["kpis"].get("profit_factor") if best_combined else None,
        "ROBUSTNESS": robustness,
        "FRAGILITY": fragility,
        "PROTECTIVE_EXIT_PRESERVED": True,
        "STOP_LOSS_DELAYED": False,
        "FORWARD_SHADOW_IMPLEMENTED": False,
        "FORWARD_SHADOW_SCHEMA": {
            "fields": [
                "candidate_id",
                "symbol",
                "baseline_exit_at",
                "shadow_exit_at",
                "baseline_pnl",
                "shadow_pnl",
                "reason",
                "provenance",
            ],
            "real_order": False,
        },
        "FORWARD_SHADOW_SAMPLE_COUNT": 0,
        "REAL_PROMOTION_RECOMMENDED": False,
        "CURRENT_REAL_POLICY_UNCHANGED": True,
        "LLM_REAL_GATE": False,
        "REAL_ORDER_MUTATION": 0,
        "POLICY_MUTATION": 0,
        "RESTART_COUNT": 0,
        "LIMITATIONS": [
            "N=35 diagnostic only — no REAL promotion",
            "1m MA evaluation — tick-level path 미복원",
            "SLIPPAGE_NOT_MODELED",
            "Entry telemetry NOT_RECORDED on most fills",
            "SIM_E0_POLICY may not match ACTUAL exit timestamps",
        ],
        "NEXT_ACTION": "COLLECT_EXIT_ENTRY_FORWARD_SHADOW_SAMPLE",
        "premature_exit_baseline_count": len(
            [t for t in trips if (t.actual_net_pnl <= 0) and not t.path_insufficient]
        ),
    }
