"""Pure churn feature/classification engine — DB 비의존, fixture replay 가능."""

from __future__ import annotations

from collections import Counter
from typing import Any

from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.constants import (
    CLS_COMPOSITE_CHURN,
    CLS_FEE_DOMINATED_CHURN,
    CLS_MA_DEAD_CROSS_REENTRY_CHURN,
    CLS_MICRO_TICK_CHURN,
    CLS_ORDER_LIFECYCLE_ANOMALY,
    CLS_RAPID_REENTRY_CHURN,
    CLS_REPEATED_LOSS_CHURN,
    CLS_TRAILING_STOP_REENTRY_CHURN,
    CLS_UNKNOWN,
    PROFILE_COMPOSITE_CHURN,
    PROFILE_FEE_CHURN,
    PROFILE_MICRO_TICK_CHURN,
    PROFILE_RAPID_REENTRY,
    PROFILE_REPEATED_LOSS,
    PROFILE_SAME_EXIT_LOOP,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    THRESHOLD_VARIANTS,
)
from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.thresholds import (
    FEE_DOMINANCE_RATIO,
    MICRO_TICK_MAX_ABS_PCT,
    MICRO_TICK_MAX_NOTIONAL_MOVE_RATIO,
    RAPID_REENTRY_SECONDS,
    SHORT_HOLD_SECONDS,
    THRESHOLD_CONFIG,
)


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def compute_signals(round_trips: list[dict[str, Any]]) -> dict[str, Any]:
    """Closed STRATEGY_OWNED RT 리스트 → forward-only churn signals.

    각 RT 기대 키:
      closed_at, opened_at, entry_price, exit_price, gross_pnl, fees, net_pnl,
      exit_reason, reentry_delay_seconds (이전 close→이번 open), holding_seconds,
      ownership_code, overlapping_skip_count, c3_shadow_decision, turnover_krw
    """

    rts = [r for r in round_trips if isinstance(r, dict)]
    n = len(rts)
    if n == 0:
        return {
            "same_symbol_round_trips": 0,
            "consecutive_losing_round_trips": 0,
            "loss_count": 0,
            "same_exit_reason_count": 0,
            "dominant_exit_reason": None,
            "reentry_delay_seconds": None,
            "min_reentry_seconds": None,
            "holding_seconds": None,
            "gross_pnl": 0.0,
            "estimated_or_actual_fee": 0.0,
            "net_pnl": 0.0,
            "turnover_krw": 0.0,
            "fee_to_gross_loss_ratio": None,
            "reentry_count_30s": 0,
            "reentry_count_60s": 0,
            "reentry_count_180s": 0,
            "reentry_count_300s": 0,
            "reentry_count_10m": 0,
            "ma_dead_cross_repeat_count": 0,
            "trailing_stop_repeat_count": 0,
            "overlapping_entry_skip_count": 0,
            "c3_shadow_decision": None,
            "micro_tick_loss_count": 0,
            "fee_dominated_count": 0,
            "rapid_reentry_count": 0,
            "entry_price": None,
            "exit_price": None,
            "exit_reason": None,
            "previous_exit_reason": None,
        }

    nets = [_f(r.get("net_pnl")) for r in rts]
    grosses = [_f(r.get("gross_pnl")) for r in rts]
    fees = [_f(r.get("fees")) for r in rts]
    turnovers = [
        _f(r.get("turnover_krw"))
        or abs(_f(r.get("entry_price")) * _f(r.get("quantity"), 1.0)) * 2
        for r in rts
    ]
    exits = [str(r.get("exit_reason") or "UNKNOWN") for r in rts]
    delays = [
        _f(r.get("reentry_delay_seconds"), default=-1.0)
        for r in rts
        if r.get("reentry_delay_seconds") is not None
    ]
    holds = [
        _f(r.get("holding_seconds"), default=-1.0)
        for r in rts
        if r.get("holding_seconds") is not None
    ]

    consec = 0
    for net in reversed(nets):
        if net < 0:
            consec += 1
        else:
            break

    loss_count = sum(1 for n_ in nets if n_ < 0)
    exit_counter = Counter(exits)
    dominant_exit, same_exit_count = exit_counter.most_common(1)[0]

    def _reentry_bucket(limit: float) -> int:
        return sum(1 for d in delays if 0 <= d <= limit)

    micro_n = 0
    fee_dom_n = 0
    rapid_n = 0
    for r, gross, fee, turn in zip(rts, grosses, fees, turnovers, strict=True):
        delay = _f(r.get("reentry_delay_seconds"), -1.0)
        hold = _f(r.get("holding_seconds"), -1.0)
        ep = _f(r.get("entry_price"))
        xp = _f(r.get("exit_price"))
        if ep > 0 and xp > 0:
            abs_pct = abs(xp - ep) / ep
            notional_move = abs(gross) / turn if turn > 0 else abs_pct
            if (
                _f(r.get("net_pnl")) < 0
                and abs_pct <= MICRO_TICK_MAX_ABS_PCT
                and notional_move <= MICRO_TICK_MAX_NOTIONAL_MOVE_RATIO
            ):
                micro_n += 1
        if gross < 0 and abs(gross) > 0 and fee / abs(gross) >= FEE_DOMINANCE_RATIO:
            if 0 <= hold <= SHORT_HOLD_SECONDS or hold < 0:
                fee_dom_n += 1
        if 0 <= delay <= RAPID_REENTRY_SECONDS:
            rapid_n += 1

    gross_sum = sum(grosses)
    fee_sum = sum(fees)
    net_sum = sum(nets)
    fee_ratio = None
    if gross_sum < 0 and abs(gross_sum) > 0:
        fee_ratio = fee_sum / abs(gross_sum)

    ma_n = sum(1 for e in exits if "MA_DEAD_CROSS" in e.upper())
    tr_n = sum(
        1
        for e in exits
        if "TRAILING" in e.upper() or e.upper() == "TRAILING_STOP"
    )
    overlap = sum(int(_f(r.get("overlapping_skip_count"), 0)) for r in rts)

    c3 = None
    for r in reversed(rts):
        if r.get("c3_shadow_decision"):
            c3 = str(r.get("c3_shadow_decision"))
            break

    last = rts[-1]
    prev_exit = exits[-2] if n >= 2 else None

    return {
        "same_symbol_round_trips": n,
        "consecutive_losing_round_trips": consec,
        "loss_count": loss_count,
        "same_exit_reason_count": int(same_exit_count),
        "dominant_exit_reason": dominant_exit,
        "reentry_delay_seconds": delays[-1] if delays else None,
        "min_reentry_seconds": min(delays) if delays else None,
        "holding_seconds": holds[-1] if holds else None,
        "gross_pnl": round(gross_sum, 4),
        "estimated_or_actual_fee": round(fee_sum, 4),
        "net_pnl": round(net_sum, 4),
        "turnover_krw": round(sum(turnovers), 4),
        "fee_to_gross_loss_ratio": (
            round(fee_ratio, 4) if fee_ratio is not None else None
        ),
        "reentry_count_30s": _reentry_bucket(30),
        "reentry_count_60s": _reentry_bucket(60),
        "reentry_count_180s": _reentry_bucket(180),
        "reentry_count_300s": _reentry_bucket(300),
        "reentry_count_10m": _reentry_bucket(600),
        "ma_dead_cross_repeat_count": ma_n,
        "trailing_stop_repeat_count": tr_n,
        "overlapping_entry_skip_count": overlap,
        "c3_shadow_decision": c3,
        "micro_tick_loss_count": micro_n,
        "fee_dominated_count": fee_dom_n,
        "rapid_reentry_count": rapid_n,
        "entry_price": last.get("entry_price"),
        "exit_price": last.get("exit_price"),
        "exit_reason": exits[-1],
        "previous_exit_reason": prev_exit,
    }


def evaluate_profiles(signals: dict[str, Any]) -> dict[str, bool]:
    """프로필별 hit 여부 (SHADOW 관찰)."""

    consec = int(signals.get("consecutive_losing_round_trips") or 0)
    rapid = int(signals.get("rapid_reentry_count") or 0)
    same_exit = int(signals.get("same_exit_reason_count") or 0)
    fee_n = int(signals.get("fee_dominated_count") or 0)
    micro_n = int(signals.get("micro_tick_loss_count") or 0)
    ma_n = int(signals.get("ma_dead_cross_repeat_count") or 0)

    a = rapid >= 2 and consec >= 1
    b = consec >= 2
    c = same_exit >= 2 and consec >= 1
    d = fee_n >= 2
    e = micro_n >= 2
    hits = {
        PROFILE_RAPID_REENTRY: a,
        PROFILE_REPEATED_LOSS: b,
        PROFILE_SAME_EXIT_LOOP: c or ma_n >= 2,
        PROFILE_FEE_CHURN: d,
        PROFILE_MICRO_TICK_CHURN: e,
    }
    hits[PROFILE_COMPOSITE_CHURN] = sum(1 for v in hits.values() if v) >= 2
    return hits


def evaluate_threshold_variants(signals: dict[str, Any]) -> dict[str, Any]:
    """S0–S3 → WOULD_ALERT | NO_ALERT (+ optional WOULD_BLOCK 기록만)."""

    consec = int(signals.get("consecutive_losing_round_trips") or 0)
    min_re = signals.get("min_reentry_seconds")
    same_exit = int(signals.get("same_exit_reason_count") or 0)
    net = _f(signals.get("net_pnl"))
    out: dict[str, Any] = {}
    for code in THRESHOLD_VARIANTS:
        cfg = THRESHOLD_CONFIG[code]
        if cfg.get("always_no_alert"):
            out[code] = {
                "label": cfg["label"],
                "WOULD_ALERT": False,
                "WOULD_BLOCK": False,
                "decision": "NO_ALERT",
            }
            continue
        lose_ok = consec >= int(cfg["losing_rt_min"] or 999)
        reentry_ok = (
            min_re is not None
            and 0 <= _f(min_re) <= float(cfg["reentry_seconds_max"] or 0)
        )
        exit_ok = same_exit >= int(cfg["same_exit_repeat_min"] or 999)
        net_ok = True
        if cfg.get("net_loss_min_krw") is not None:
            net_ok = net <= -float(cfg["net_loss_min_krw"])
        if cfg.get("require_compound"):
            alert = lose_ok and (reentry_ok or exit_ok) and net_ok
        else:
            alert = lose_ok and (reentry_ok or exit_ok)
            if cfg.get("net_loss_min_krw") is not None:
                alert = alert and net_ok
        out[code] = {
            "label": cfg["label"],
            "WOULD_ALERT": bool(alert),
            "WOULD_BLOCK": bool(alert),  # 기록만 — 실제 block 금지
            "decision": "WOULD_ALERT" if alert else "NO_ALERT",
        }
    return out


def classify(
    signals: dict[str, Any],
    *,
    profiles: dict[str, bool] | None = None,
) -> tuple[str, list[str]]:
    """PRIMARY / SECONDARY classification."""

    profiles = profiles or evaluate_profiles(signals)
    secondaries: list[str] = []

    if int(signals.get("overlapping_entry_skip_count") or 0) > 0:
        # #126 lifecycle anomaly — 일반 정책 churn과 분리
        return CLS_ORDER_LIFECYCLE_ANOMALY, secondaries

    ma_n = int(signals.get("ma_dead_cross_repeat_count") or 0)
    tr_n = int(signals.get("trailing_stop_repeat_count") or 0)
    consec = int(signals.get("consecutive_losing_round_trips") or 0)

    candidates: list[tuple[int, str]] = []
    if profiles.get(PROFILE_COMPOSITE_CHURN):
        candidates.append((100, CLS_COMPOSITE_CHURN))
    if ma_n >= 2 and consec >= 2:
        candidates.append((90, CLS_MA_DEAD_CROSS_REENTRY_CHURN))
    if tr_n >= 2 and consec >= 2:
        candidates.append((85, CLS_TRAILING_STOP_REENTRY_CHURN))
    if profiles.get(PROFILE_RAPID_REENTRY):
        candidates.append((80, CLS_RAPID_REENTRY_CHURN))
    if profiles.get(PROFILE_MICRO_TICK_CHURN):
        candidates.append((75, CLS_MICRO_TICK_CHURN))
    if profiles.get(PROFILE_FEE_CHURN):
        candidates.append((70, CLS_FEE_DOMINATED_CHURN))
    if profiles.get(PROFILE_REPEATED_LOSS):
        candidates.append((60, CLS_REPEATED_LOSS_CHURN))

    if not candidates:
        # 단독 1회 손실/재진입은 UNKNOWN (확정 금지)
        return CLS_UNKNOWN, []

    candidates.sort(key=lambda x: -x[0])
    primary = candidates[0][1]
    secondaries = [c[1] for c in candidates[1:4] if c[1] != primary]
    return primary, secondaries


def severity_for(
    signals: dict[str, Any],
    *,
    variants: dict[str, Any] | None = None,
    cycle_still_active: bool = False,
) -> str:
    variants = variants or evaluate_threshold_variants(signals)
    consec = int(signals.get("consecutive_losing_round_trips") or 0)
    net = _f(signals.get("net_pnl"))
    s3 = bool((variants.get("S3") or {}).get("WOULD_ALERT"))
    s2 = bool((variants.get("S2") or {}).get("WOULD_ALERT"))
    s1 = bool((variants.get("S1") or {}).get("WOULD_ALERT"))

    if s3 or (consec >= 4 and net <= -200 and cycle_still_active):
        return SEVERITY_CRITICAL
    if s2 or (consec >= 3 and (s1 or cycle_still_active)):
        return SEVERITY_WARNING
    if s1 or consec >= 2:
        return SEVERITY_INFO
    return SEVERITY_INFO


def should_alert_episode(
    signals: dict[str, Any],
    *,
    variants: dict[str, Any] | None = None,
) -> bool:
    """Episode 생성/유지 — balanced(S2) 또는 sensitive(S1)+복합 evidence."""

    variants = variants or evaluate_threshold_variants(signals)
    if bool((variants.get("S2") or {}).get("WOULD_ALERT")):
        return True
    if bool((variants.get("S3") or {}).get("WOULD_ALERT")):
        return True
    # S1 alone: require at least 2 profile hits (false positive 억제)
    if bool((variants.get("S1") or {}).get("WOULD_ALERT")):
        hits = sum(1 for v in evaluate_profiles(signals).values() if v)
        return hits >= 2
    return False


def evaluate_round_trips(
    round_trips: list[dict[str, Any]],
    *,
    cycle_still_active: bool = False,
) -> dict[str, Any]:
    signals = compute_signals(round_trips)
    profiles = evaluate_profiles(signals)
    variants = evaluate_threshold_variants(signals)
    primary, secondary = classify(signals, profiles=profiles)
    sev = severity_for(
        signals, variants=variants, cycle_still_active=cycle_still_active
    )
    return {
        "signals": signals,
        "profiles": profiles,
        "threshold_variants": variants,
        "primary_classification": primary,
        "secondary_classifications": secondary,
        "severity": sev,
        "should_alert": should_alert_episode(signals, variants=variants),
    }
