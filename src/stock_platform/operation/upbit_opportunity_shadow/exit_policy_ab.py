"""Shadow/Paper Exit Policy A/B — Baseline vs Candidate A (REAL 정책 미변경).

동일 entry에서 두 exit 정책만 시간순으로 재현한다.
Lookahead 금지: 분봉 내 SL → TP → TRAILING → MA 순(보호 우선 + 상승 후 조정).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from typing import Any, Sequence

from stock_platform.broker.fee_policy import UpbitFeePolicy
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    MinuteBar,
    as_utc,
    floor_minute,
    return_pct,
)
from stock_platform.realtime.ma_exit_policy import (
    DEFAULT_EXIT_MIN_MA_SEPARATION_PCT,
    DEFAULT_MA_EXIT_MIN_HOLDING_SECONDS,
    is_dead_cross_confirmed,
    is_min_holding_satisfied,
)

# ── 정책 상수 (grid search 금지 — 이 두 개만) ──────────────────────────────

POLICY_BASELINE = "BASELINE"
POLICY_CANDIDATE_A = "CANDIDATE_A"

DEFAULT_NOTIONAL_KRW = Decimal("10000")
DEFAULT_HORIZON_MINUTES = 60
MA_SHORT = 5
MA_LONG = 20
FORWARD_SAMPLE_MIN = 30

VERDICT_RUNNING = "TP_TRAIL_AB_SHADOW_VALIDATION_RUNNING"
VERDICT_VALIDATED = "TP_TRAIL_CANDIDATE_A_FORWARD_VALIDATED"
VERDICT_REJECTED = "TP_TRAIL_CANDIDATE_A_REJECTED"

NEXT_COLLECT = "COLLECT_FORWARD_SHADOW_AB_SAMPLE"
NEXT_REVIEW = "REVIEW_CANDIDATE_A_FOR_REAL_PROMOTION"
NEXT_KEEP_BASELINE = "KEEP_BASELINE_EXIT_POLICY"


@dataclass(frozen=True, slots=True)
class ExitPolicySpec:
    """Exit-only 스펙. Entry/MA anti-churn/SL 값은 명시적 고정."""

    label: str
    tp_pct: float
    sl_pct: float
    trail_distance_pct: float
    # None이면 REAL과 동일: highest>entry 만으로 trailing 가능
    trail_activation_pct: float | None
    ma_exit_enabled: bool = True
    exit_min_ma_separation_pct: float = DEFAULT_EXIT_MIN_MA_SEPARATION_PCT
    ma_exit_min_holding_seconds: int = DEFAULT_MA_EXIT_MIN_HOLDING_SECONDS


BASELINE_SPEC = ExitPolicySpec(
    label=POLICY_BASELINE,
    tp_pct=10.0,
    sl_pct=5.0,
    trail_distance_pct=3.0,
    trail_activation_pct=None,
)

CANDIDATE_A_SPEC = ExitPolicySpec(
    label=POLICY_CANDIDATE_A,
    tp_pct=1.0,
    sl_pct=5.0,
    trail_distance_pct=0.3,
    trail_activation_pct=0.5,
)


@dataclass(frozen=True, slots=True)
class ExitSimResult:
    policy: str
    symbol: str
    entry_at: datetime
    entry_price: Decimal
    exit_at: datetime | None
    exit_price: Decimal | None
    exit_reason: str
    holding_seconds: float | None
    gross_return_pct: float | None
    estimated_fee_krw: float
    net_return_pct: float | None
    gross_pnl_krw: float
    net_pnl_krw: float
    mfe_pct: float | None
    mae_pct: float | None
    trail_activated: bool
    fee_only_loss: bool
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "symbol": self.symbol,
            "entry_at": as_utc(self.entry_at).isoformat(),
            "entry_price": float(self.entry_price),
            "exit_at": (
                as_utc(self.exit_at).isoformat() if self.exit_at else None
            ),
            "exit_price": (
                float(self.exit_price) if self.exit_price is not None else None
            ),
            "exit_reason": self.exit_reason,
            "holding_seconds": self.holding_seconds,
            "gross_return_pct": self.gross_return_pct,
            "estimated_fee_krw": self.estimated_fee_krw,
            "net_return_pct": self.net_return_pct,
            "gross_pnl_krw": self.gross_pnl_krw,
            "net_pnl_krw": self.net_pnl_krw,
            "mfe_pct": self.mfe_pct,
            "mae_pct": self.mae_pct,
            "trail_activated": self.trail_activated,
            "fee_only_loss": self.fee_only_loss,
            "detail": self.detail,
        }


def _sma(closes: Sequence[Decimal], end_idx: int, window: int) -> Decimal | None:
    """end_idx 포함 최근 window개 종가 SMA. 부족하면 None."""

    if window <= 0 or end_idx < window - 1:
        return None
    chunk = closes[end_idx - window + 1 : end_idx + 1]
    if len(chunk) < window:
        return None
    return sum(chunk, Decimal("0")) / Decimal(str(window))


def _fee_bundle(
    *,
    entry: Decimal,
    exit_price: Decimal,
    notional: Decimal,
    fee_rate: Decimal,
) -> dict[str, float]:
    """Upbit taker 왕복 fee + gross/net (KRW)."""

    if entry <= 0 or notional <= 0:
        return {
            "qty": 0.0,
            "buy_fee": 0.0,
            "sell_fee": 0.0,
            "fee_total": 0.0,
            "gross_pnl": 0.0,
            "net_pnl": 0.0,
            "gross_return_pct": 0.0,
            "net_return_pct": 0.0,
        }
    qty = notional / entry
    buy_notional = entry * qty
    sell_notional = exit_price * qty
    buy_fee = buy_notional * fee_rate
    sell_fee = sell_notional * fee_rate
    gross = sell_notional - buy_notional
    net = gross - buy_fee - sell_fee
    entry_cost = buy_notional + buy_fee
    gross_ret = float((exit_price - entry) / entry * Decimal("100"))
    net_ret = float(net / entry_cost * Decimal("100")) if entry_cost > 0 else 0.0
    return {
        "qty": float(qty),
        "buy_fee": float(buy_fee),
        "sell_fee": float(sell_fee),
        "fee_total": float(buy_fee + sell_fee),
        "gross_pnl": float(gross),
        "net_pnl": float(net),
        "gross_return_pct": gross_ret,
        "net_return_pct": net_ret,
    }


def simulate_exit_policy(
    bars: Sequence[MinuteBar],
    *,
    symbol: str,
    entry_at: datetime,
    entry_price: Decimal,
    spec: ExitPolicySpec,
    now: datetime | None = None,
    horizon_minutes: int = DEFAULT_HORIZON_MINUTES,
    notional_krw: Decimal = DEFAULT_NOTIONAL_KRW,
    fee_rate: Decimal | None = None,
) -> ExitSimResult:
    """단일 exit 정책을 1m OHLC 경로로 재현. 미래 바 금지."""

    entry = Decimal(str(entry_price))
    t0 = as_utc(entry_at)
    now_utc = as_utc(now or datetime.now(timezone.utc))
    horizon_end = t0 + timedelta(minutes=int(horizon_minutes))
    rate = fee_rate if fee_rate is not None else UpbitFeePolicy.DEFAULT_TAKER_RATE

    tp_price = entry * (
        Decimal("1") + Decimal(str(abs(spec.tp_pct))) / Decimal("100")
    )
    sl_price = entry * (
        Decimal("1") - Decimal(str(abs(spec.sl_pct))) / Decimal("100")
    )
    activation_price: Decimal | None = None
    if spec.trail_activation_pct is not None:
        activation_price = entry * (
            Decimal("1")
            + Decimal(str(abs(spec.trail_activation_pct))) / Decimal("100")
        )
    trail_frac = Decimal(str(abs(spec.trail_distance_pct))) / Decimal("100")

    # entry 분봉부터 시계열 (warmup용 이전 바는 MA만)
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
    # activation 없는 baseline: highest>entry 조건과 동일하게 진입 직후 HW=entry
    mfe: Decimal | None = None
    mae: Decimal | None = None
    exit_reason = "WINDOW_END"
    exit_at: datetime | None = None
    exit_price: Decimal | None = None
    bars_checked = 0

    for idx, bar in enumerate(ordered):
        at = as_utc(bar.candle_at)
        if at < start_floor:
            continue
        bars_checked += 1

        # MFE/MAE (보유 중)
        high_exc = return_pct(entry, bar.high)
        low_exc = return_pct(entry, bar.low)
        mfe = high_exc if mfe is None else max(mfe, high_exc)
        mae = low_exc if mae is None else min(mae, low_exc)

        # high_water / activation (이 봉 high 반영 — trail은 이후 체크)
        if bar.high > high_water:
            high_water = bar.high
        if activation_price is None:
            # Baseline: highest > entry 이면 trailing 검사 가능
            if high_water > entry:
                trail_active = True
        else:
            if (not trail_active) and bar.high >= activation_price:
                trail_active = True

        trail_trigger = high_water * (Decimal("1") - trail_frac)

        # 분봉 내 우선순위: SL → TP → TRAILING → MA (lookahead 유리 선택 금지)
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
            # activation 전에 trail_active가 False면 여기 진입 불가 (Candidate A)
            exit_reason = "TRAILING_STOP"
            exit_at = at
            exit_price = trail_trigger
            break

        if spec.ma_exit_enabled:
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
            if raw_dead and hold_ok and sep_ok:
                exit_reason = "MA_DEAD_CROSS"
                exit_at = at
                exit_price = bar.close
                break
    else:
        # 창 종료 — 마지막 완료 봉 close
        post = [b for b in ordered if as_utc(b.candle_at) >= start_floor]
        if post:
            last = post[-1]
            exit_at = as_utc(last.candle_at)
            exit_price = last.close
            exit_reason = "WINDOW_END"
        else:
            exit_reason = "NO_BARS"
            exit_at = None
            exit_price = None

    holding: float | None = None
    if exit_at is not None:
        holding = max(0.0, (as_utc(exit_at) - t0).total_seconds())

    if exit_price is None:
        return ExitSimResult(
            policy=spec.label,
            symbol=symbol,
            entry_at=t0,
            entry_price=entry,
            exit_at=None,
            exit_price=None,
            exit_reason=exit_reason,
            holding_seconds=holding,
            gross_return_pct=None,
            estimated_fee_krw=0.0,
            net_return_pct=None,
            gross_pnl_krw=0.0,
            net_pnl_krw=0.0,
            mfe_pct=float(mfe) if mfe is not None else None,
            mae_pct=float(mae) if mae is not None else None,
            trail_activated=trail_active,
            fee_only_loss=False,
            detail={
                "bars_checked": bars_checked,
                "tp_price": float(tp_price),
                "sl_price": float(sl_price),
                "trail_activation_pct": spec.trail_activation_pct,
                "trail_distance_pct": spec.trail_distance_pct,
            },
        )

    fees = _fee_bundle(
        entry=entry,
        exit_price=Decimal(str(exit_price)),
        notional=Decimal(str(notional_krw)),
        fee_rate=Decimal(str(rate)),
    )
    fee_only = (
        fees["gross_pnl"] >= -1e-9
        and fees["net_pnl"] < 0
    )

    return ExitSimResult(
        policy=spec.label,
        symbol=symbol,
        entry_at=t0,
        entry_price=entry,
        exit_at=exit_at,
        exit_price=Decimal(str(exit_price)),
        exit_reason=exit_reason,
        holding_seconds=holding,
        gross_return_pct=fees["gross_return_pct"],
        estimated_fee_krw=fees["fee_total"],
        net_return_pct=fees["net_return_pct"],
        gross_pnl_krw=fees["gross_pnl"],
        net_pnl_krw=fees["net_pnl"],
        mfe_pct=float(mfe) if mfe is not None else None,
        mae_pct=float(mae) if mae is not None else None,
        trail_activated=trail_active,
        fee_only_loss=fee_only,
        detail={
            "bars_checked": bars_checked,
            "tp_price": float(tp_price),
            "sl_price": float(sl_price),
            "high_water": float(high_water),
            "trail_activation_pct": spec.trail_activation_pct,
            "trail_distance_pct": spec.trail_distance_pct,
            "fee": fees,
            "notional_krw": float(notional_krw),
            "horizon_minutes": int(horizon_minutes),
        },
    )


def compare_exit_policies_ab(
    bars: Sequence[MinuteBar],
    *,
    symbol: str,
    entry_at: datetime,
    entry_price: Decimal,
    now: datetime | None = None,
    horizon_minutes: int = DEFAULT_HORIZON_MINUTES,
    notional_krw: Decimal = DEFAULT_NOTIONAL_KRW,
) -> dict[str, Any]:
    """동일 entry로 Baseline + Candidate A 동시 재현."""

    baseline = simulate_exit_policy(
        bars,
        symbol=symbol,
        entry_at=entry_at,
        entry_price=entry_price,
        spec=BASELINE_SPEC,
        now=now,
        horizon_minutes=horizon_minutes,
        notional_krw=notional_krw,
    )
    candidate = simulate_exit_policy(
        bars,
        symbol=symbol,
        entry_at=entry_at,
        entry_price=entry_price,
        spec=CANDIDATE_A_SPEC,
        now=now,
        horizon_minutes=horizon_minutes,
        notional_krw=notional_krw,
    )
    return {
        "schema": "exit_policy_ab_v1",
        "same_entry": True,
        "symbol": symbol,
        "entry_at": as_utc(entry_at).isoformat(),
        "entry_price": float(entry_price),
        "baseline": baseline.to_dict(),
        "candidate_a": candidate.to_dict(),
        "real_order": False,
        "real_policy_mutation": False,
    }


def _arm_kpis(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """단일 정책 arm KPI."""

    n = len(results)
    if n == 0:
        return {
            "sample_count": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "gross_pnl": 0.0,
            "fees": 0.0,
            "net_pnl": 0.0,
            "avg_return": None,
            "median_return": None,
            "profit_factor": None,
            "avg_win": None,
            "avg_loss": None,
            "max_trade_loss": None,
            "max_drawdown_proxy": None,
            "avg_holding_seconds": None,
            "tp_exit_count": 0,
            "trailing_exit_count": 0,
            "ma_exit_count": 0,
            "sl_count": 0,
            "fee_only_loss_count": 0,
            "window_end_count": 0,
        }

    nets = [float(r.get("net_pnl_krw") or 0.0) for r in results]
    rets = [
        float(r["net_return_pct"])
        for r in results
        if r.get("net_return_pct") is not None
    ]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    holds = [
        float(r["holding_seconds"])
        for r in results
        if r.get("holding_seconds") is not None
    ]

    def _reason_count(name: str) -> int:
        return sum(1 for r in results if r.get("exit_reason") == name)

    gross_wins = sum(wins) if wins else 0.0
    gross_losses = abs(sum(losses)) if losses else 0.0
    pf = (
        round(gross_wins / gross_losses, 4)
        if gross_losses > 0
        else (None if not wins else float("inf"))
    )
    # equity curve proxy (trade 순)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for x in nets:
        equity += x
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)

    return {
        "sample_count": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n, 4) if n else None,
        "gross_pnl": round(sum(float(r.get("gross_pnl_krw") or 0) for r in results), 4),
        "fees": round(sum(float(r.get("estimated_fee_krw") or 0) for r in results), 4),
        "net_pnl": round(sum(nets), 4),
        "avg_return": round(sum(rets) / len(rets), 6) if rets else None,
        "median_return": round(float(median(rets)), 6) if rets else None,
        "profit_factor": pf if pf != float("inf") else None,
        "avg_win": round(sum(wins) / len(wins), 4) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else None,
        "max_trade_loss": round(min(nets), 4) if nets else None,
        "max_drawdown_proxy": round(max_dd, 4),
        "avg_holding_seconds": (
            round(sum(holds) / len(holds), 2) if holds else None
        ),
        "tp_exit_count": _reason_count("TAKE_PROFIT"),
        "trailing_exit_count": _reason_count("TRAILING_STOP"),
        "ma_exit_count": _reason_count("MA_DEAD_CROSS"),
        "sl_count": _reason_count("STOP_LOSS"),
        "fee_only_loss_count": sum(
            1 for r in results if r.get("fee_only_loss")
        ),
        "window_end_count": _reason_count("WINDOW_END"),
    }


def analyze_missed_winners(
    pairs: Sequence[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    """Candidate가 TP/Trail로 조기 청산해 Baseline보다 net이 낮은 케이스."""

    cut_early = 0
    protected_small = 0
    for base, cand in pairs:
        b_net = float(base.get("net_pnl_krw") or 0)
        c_net = float(cand.get("net_pnl_krw") or 0)
        b_ret = float(base.get("gross_return_pct") or 0)
        c_reason = str(cand.get("exit_reason") or "")
        if c_reason in {"TAKE_PROFIT", "TRAILING_STOP"} and c_net < b_net:
            cut_early += 1
        if (
            c_reason in {"TAKE_PROFIT", "TRAILING_STOP"}
            and b_ret > 0
            and str(base.get("exit_reason") or "") == "MA_DEAD_CROSS"
            and c_net > b_net
        ):
            protected_small += 1
    return {
        "candidate_cut_larger_winner_count": cut_early,
        "candidate_protected_pre_ma_profit_count": protected_small,
    }


def decide_candidate_superiority(
    *,
    baseline_kpi: dict[str, Any],
    candidate_kpi: dict[str, Any],
    sample_count: int,
) -> dict[str, Any]:
    """승격 후보 판정 — 한 조건만 좋아도 REAL 추천 금지."""

    if sample_count < FORWARD_SAMPLE_MIN:
        return {
            "candidate_superiority": "INSUFFICIENT",
            "final_verdict": VERDICT_RUNNING,
            "next_action": NEXT_COLLECT,
            "reasons": ["INSUFFICIENT_FORWARD_SAMPLE"],
        }

    reasons: list[str] = []
    net_ok = float(candidate_kpi.get("net_pnl") or 0) > float(
        baseline_kpi.get("net_pnl") or 0
    )
    fee_churn_ok = int(candidate_kpi.get("fee_only_loss_count") or 0) <= int(
        baseline_kpi.get("fee_only_loss_count") or 0
    )
    b_max = float(baseline_kpi.get("max_trade_loss") or 0)
    c_max = float(candidate_kpi.get("max_trade_loss") or 0)
    # max_trade_loss는 음수(손실). Candidate가 더 작으면(더 음수) 악화.
    # 25% 이상 악화면 fail.
    if b_max < 0:
        max_loss_ok = c_max >= (b_max * 1.25)
    else:
        max_loss_ok = c_max >= b_max

    # protective: baseline SL이 있으면 candidate도 SL 경로가 죽지 않았는지
    safety_ok = True
    if int(baseline_kpi.get("sl_count") or 0) > 0:
        safety_ok = int(candidate_kpi.get("sl_count") or 0) > 0

    if not net_ok:
        reasons.append("NET_RETURN_NOT_BETTER")
    if not fee_churn_ok:
        reasons.append("FEE_ONLY_CHURN_WORSE")
    if not max_loss_ok:
        reasons.append("MAX_LOSS_WORSENED")
    if not safety_ok:
        reasons.append("PROTECTIVE_SAFETY_REGRESSION")

    superior = net_ok and fee_churn_ok and max_loss_ok and safety_ok
    if superior:
        return {
            "candidate_superiority": "YES",
            "final_verdict": VERDICT_VALIDATED,
            "next_action": NEXT_REVIEW,
            "reasons": ["ALL_PROMOTION_GATES_PASSED"],
            "gates": {
                "net_ok": net_ok,
                "fee_churn_ok": fee_churn_ok,
                "max_loss_ok": max_loss_ok,
                "safety_ok": safety_ok,
            },
        }
    return {
        "candidate_superiority": "NO",
        "final_verdict": VERDICT_REJECTED,
        "next_action": NEXT_KEEP_BASELINE,
        "reasons": reasons or ["CANDIDATE_NOT_SUPERIOR"],
        "gates": {
            "net_ok": net_ok,
            "fee_churn_ok": fee_churn_ok,
            "max_loss_ok": max_loss_ok,
            "safety_ok": safety_ok,
        },
    }


def aggregate_ab_pairs(
    pairs: Sequence[dict[str, Any]],
    *,
    cohort: str = "FORWARD_SHADOW",
) -> dict[str, Any]:
    """[{baseline, candidate_a, ...}, ...] → KPI + verdict."""

    baselines = [p["baseline"] for p in pairs if p.get("baseline")]
    candidates = [p["candidate_a"] for p in pairs if p.get("candidate_a")]
    n = min(len(baselines), len(candidates))
    baselines = baselines[:n]
    candidates = candidates[:n]
    base_kpi = _arm_kpis(baselines)
    cand_kpi = _arm_kpis(candidates)
    missed = analyze_missed_winners(list(zip(baselines, candidates, strict=True)))
    decision = decide_candidate_superiority(
        baseline_kpi=base_kpi,
        candidate_kpi=cand_kpi,
        sample_count=n,
    )
    return {
        "cohort": cohort,
        "sample_count": n,
        "baseline": base_kpi,
        "candidate_a": cand_kpi,
        "missed_winner_analysis": missed,
        "fee_churn_comparison": {
            "baseline_fee_only_loss_count": base_kpi["fee_only_loss_count"],
            "candidate_fee_only_loss_count": cand_kpi["fee_only_loss_count"],
            "baseline_fees": base_kpi["fees"],
            "candidate_fees": cand_kpi["fees"],
        },
        "avg_holding_comparison": {
            "baseline": base_kpi["avg_holding_seconds"],
            "candidate_a": cand_kpi["avg_holding_seconds"],
        },
        "max_loss_comparison": {
            "baseline": base_kpi["max_trade_loss"],
            "candidate_a": cand_kpi["max_trade_loss"],
        },
        **decision,
    }


def summarize_exit_ab_from_shadows(
    rows: Sequence[Any],
) -> dict[str, Any]:
    """COMPLETED shadow evaluation_detail.exit_ab 집계."""

    pairs: list[dict[str, Any]] = []
    for row in rows:
        detail = getattr(row, "evaluation_detail", None) or {}
        if not isinstance(detail, dict):
            continue
        ab = detail.get("exit_ab")
        if not isinstance(ab, dict):
            continue
        if not ab.get("baseline") or not ab.get("candidate_a"):
            continue
        # COMPLETED만 — WINDOW_END/청산 모두 포함 (경로 완료 표본)
        pairs.append(ab)
    summary = aggregate_ab_pairs(pairs, cohort="FORWARD_SHADOW")
    summary["exit_ab_present_count"] = len(pairs)
    return summary
