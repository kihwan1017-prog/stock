"""Upbit MA exit forward shadow — core service (REAL mutation 0)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.fee_policy import UpbitFeePolicy
from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.constants import (
    CONFIRM_EVALUATIONS,
    EARLY_DUMP_SECONDS,
    PRIMARY_SHADOW_RULE,
    PROTECTIVE_EXIT_REASONS,
    RESEARCH_ONLY_LABEL,
    RULE_VERSION,
    SECONDARY_A_RULE,
    SECONDARY_A_SEP_PCT,
    SECONDARY_B_FEE_EDGE_PCT,
    SECONDARY_B_RULE,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_PRE_EXISTING_EXCLUDED,
    STATUS_SHADOW_TRACKING,
)
from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.entities import (
    UpbitMaExitForwardShadowEntity,
)
from stock_platform.realtime.ma_exit_policy import (
    MaExitThresholds,
    estimate_fee_aware_exit,
    is_dead_cross_confirmed,
    is_min_holding_satisfied,
    is_protective_exit_reason,
)

ZERO = Decimal("0")
ONE = Decimal("1")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def shadow_enabled(settings: Any | None = None) -> bool:
    settings = settings or get_settings()
    return bool(getattr(settings, "upbit_ma_exit_forward_shadow_enabled", True))


def deployment_epoch(settings: Any | None = None) -> datetime:
    """cohort 시작 시각 — 설정 없으면 모듈 최초 enable 시점(UTC now fallback)."""

    settings = settings or get_settings()
    raw = str(getattr(settings, "upbit_ma_exit_forward_shadow_deployed_at", "") or "").strip()
    if raw:
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            return datetime.fromisoformat(raw).astimezone(timezone.utc)
        except ValueError:
            pass
    return _utc_now()


def compute_round_trip_pnl(
    *,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
    buy_fee: Decimal | None = None,
    fee_rate: Decimal | None = None,
) -> dict[str, float]:
    """가상/실제 공통 fee schedule."""

    rate = fee_rate or UpbitFeePolicy.DEFAULT_TAKER_RATE
    notional = entry_price * quantity
    buy_f = buy_fee if buy_fee is not None else (notional * rate)
    exit_value = exit_price * quantity
    sell_f = exit_value * rate
    gross = exit_value - notional
    total_fee = buy_f + sell_f
    net = exit_value - sell_f - notional - buy_f
    return {
        "gross_pnl": float(gross),
        "fee": float(total_fee),
        "net_pnl": float(net),
    }


def _load_state(row: UpbitMaExitForwardShadowEntity) -> dict[str, Any]:
    return dict(row.shadow_state_json or {})


def _save_state(row: UpbitMaExitForwardShadowEntity, state: dict[str, Any]) -> None:
    row.shadow_state_json = state
    row.context_as_of = _utc_now()


def _init_secondary() -> dict[str, Any]:
    return {
        SECONDARY_A_RULE: {
            "rule": SECONDARY_A_RULE,
            "sep_pct": SECONDARY_A_SEP_PCT,
            "confirm_streak": 0,
            "first_dead_cross_at": None,
            "exit_at": None,
            "exit_price": None,
            "exit_reason": None,
            "net_pnl": None,
        },
        SECONDARY_B_RULE: {
            "rule": SECONDARY_B_RULE,
            "fee_edge_pct": SECONDARY_B_FEE_EDGE_PCT,
            "virtual_entry_skip": False,
            "virtual_skip_reason": None,
            "note": "REAL entry unchanged — virtual skip only",
        },
    }


def enroll_on_position_open(
    session: Session,
    *,
    user_broker_account_id: int,
    binding_id: int,
    symbol: str,
    strategy_id: int | None,
    entry_order_id: int | None,
    entry_at: datetime,
    entry_price: Decimal,
    entry_quantity: Decimal | None = None,
    entry_fee: Decimal | None = None,
    entry_fill_id: int | None = None,
    settings: Any | None = None,
) -> dict[str, Any]:
    """새 REAL 포지션 open 시 cohort 등록 — 중복 binding 방지."""

    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}

    existing = session.scalar(
        select(UpbitMaExitForwardShadowEntity).where(
            UpbitMaExitForwardShadowEntity.binding_id == int(binding_id)
        )
    )
    if existing is not None:
        return {
            "ok": True,
            "duplicate": True,
            "shadow_row_id": int(existing.shadow_row_id),
        }

    deploy = deployment_epoch(settings)
    opened = _as_utc(entry_at) or _utc_now()
    status = STATUS_ACTIVE
    if opened < deploy:
        status = STATUS_PRE_EXISTING_EXCLUDED

    row = UpbitMaExitForwardShadowEntity(
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=strategy_id,
        symbol=str(symbol).upper(),
        binding_id=int(binding_id),
        entry_order_id=entry_order_id,
        entry_fill_id=entry_fill_id,
        entry_at=opened,
        entry_price=entry_price,
        entry_quantity=entry_quantity,
        entry_fee=entry_fee,
        rule_version=RULE_VERSION,
        status=status,
        research_only=True,
        shadow_rule=PRIMARY_SHADOW_RULE,
        secondary_shadow_json=_init_secondary(),
        shadow_state_json={
            "confirm_streak": 0,
            "high_water": str(entry_price),
            "trail_active": False,
            "research_label": RESEARCH_ONLY_LABEL,
            "stop_loss_delayed": False,
            "kill_delayed": False,
            "risk_delayed": False,
        },
    )
    try:
        from stock_platform.trading.autotrading_data_trust import (
            resolve_open_window_attribution,
        )

        attr = resolve_open_window_attribution(
            session, market="UPBIT", uba_id=int(user_broker_account_id)
        )
        row.data_quality_status = attr["data_quality_status"]
        row.included_in_research_metrics = attr["included_in_research_metrics"]
        row.quarantine_reason = attr["quarantine_reason"]
        row.quality_window_id = attr["quality_window_id"]
    except Exception:
        pass
    session.add(row)
    session.flush()

    # Secondary B — entry 시점 fee-edge 가상 skip (REAL entry 변경 없음)
    sec = dict(row.secondary_shadow_json or {})
    fee_snap = estimate_fee_aware_exit(
        entry_price=entry_price,
        quantity=entry_quantity or ZERO,
        current_price=entry_price,
        buy_fee=entry_fee,
    )
    ret_pct = fee_snap.get("estimated_net_return_pct")
    sec_b = dict(sec.get(SECONDARY_B_RULE) or {})
    if ret_pct is not None and float(ret_pct) < SECONDARY_B_FEE_EDGE_PCT:
        sec_b["virtual_entry_skip"] = True
        sec_b["virtual_skip_reason"] = "FEE_EDGE_BELOW_0.10"
    sec[SECONDARY_B_RULE] = sec_b
    row.secondary_shadow_json = sec

    return {
        "ok": True,
        "shadow_row_id": int(row.shadow_row_id),
        "status": status,
        "pre_existing": status == STATUS_PRE_EXISTING_EXCLUDED,
    }


def _find_trackable_row(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    binding_id: int | None = None,
) -> UpbitMaExitForwardShadowEntity | None:
    sym = str(symbol).upper()
    q = select(UpbitMaExitForwardShadowEntity).where(
        UpbitMaExitForwardShadowEntity.user_broker_account_id
        == int(user_broker_account_id),
        UpbitMaExitForwardShadowEntity.symbol == sym,
        UpbitMaExitForwardShadowEntity.status.in_(
            [STATUS_ACTIVE, STATUS_SHADOW_TRACKING]
        ),
    )
    if binding_id is not None:
        q = q.where(
            UpbitMaExitForwardShadowEntity.binding_id == int(binding_id)
        )
    return session.scalar(q.order_by(UpbitMaExitForwardShadowEntity.shadow_row_id.desc()))


def _record_baseline(
    row: UpbitMaExitForwardShadowEntity,
    *,
    exit_reason: str,
    exit_at: datetime,
    exit_price: Decimal,
    gross_pnl: float | None = None,
    fee: float | None = None,
    net_pnl: float | None = None,
) -> None:
    if row.baseline_exit_at is not None:
        return
    qty = row.entry_quantity or ZERO
    if net_pnl is None:
        pnl = compute_round_trip_pnl(
            entry_price=row.entry_price,
            exit_price=exit_price,
            quantity=qty if qty > ZERO else ONE,
            buy_fee=row.entry_fee,
        )
        gross_pnl = pnl["gross_pnl"]
        fee = pnl["fee"]
        net_pnl = pnl["net_pnl"]
    row.baseline_exit_reason = str(exit_reason).upper()
    row.baseline_exit_at = _as_utc(exit_at)
    row.baseline_exit_price = exit_price
    row.baseline_gross_pnl = Decimal(str(gross_pnl))
    row.baseline_fee = Decimal(str(fee))
    row.baseline_net_pnl = Decimal(str(net_pnl))


def _complete_shadow(
    row: UpbitMaExitForwardShadowEntity,
    *,
    exit_reason: str,
    exit_at: datetime,
    exit_price: Decimal,
    delayed_loss: bool = False,
) -> None:
    if row.shadow_exit_at is not None:
        return
    qty = row.entry_quantity or ONE
    pnl = compute_round_trip_pnl(
        entry_price=row.entry_price,
        exit_price=exit_price,
        quantity=qty,
        buy_fee=row.entry_fee,
    )
    row.shadow_exit_reason = str(exit_reason).upper()
    row.shadow_exit_at = _as_utc(exit_at)
    row.shadow_exit_price = exit_price
    row.shadow_gross_pnl = Decimal(str(pnl["gross_pnl"]))
    row.shadow_fee = Decimal(str(pnl["fee"]))
    row.shadow_net_pnl = Decimal(str(pnl["net_pnl"]))
    if row.baseline_net_pnl is not None:
        row.difference_net = row.shadow_net_pnl - row.baseline_net_pnl
    row.status = STATUS_COMPLETED
    row.completed_at = _utc_now()
    state = _load_state(row)
    if delayed_loss:
        state["extra_loss_from_delay"] = True
        state["confirm2_delayed_loss_count"] = int(
            state.get("confirm2_delayed_loss_count") or 0
        ) + 1
    _save_state(row, state)


def _check_protective_exit(
    *,
    row: UpbitMaExitForwardShadowEntity,
    price: Decimal,
    event_time: datetime,
    stop_loss_ratio: Decimal,
    take_profit_ratio: Decimal,
    trail_distance_ratio: Decimal,
    state: dict[str, Any],
) -> str | None:
    """SL/TP/TRAIL — confirmation 무시, 즉시 shadow exit."""

    entry = row.entry_price
    high_raw = state.get("high_water")
    high_water = Decimal(str(high_raw)) if high_raw else entry
    if price > high_water:
        high_water = price
        state["high_water"] = str(high_water)
    trail_active = high_water > entry
    state["trail_active"] = trail_active

    sl_price = entry * (ONE - stop_loss_ratio)
    tp_price = entry * (ONE + take_profit_ratio)
    trail_trigger = high_water * (ONE - trail_distance_ratio)

    if price <= sl_price:
        return "STOP_LOSS"
    if price >= tp_price:
        return "TAKE_PROFIT"
    if trail_active and price <= trail_trigger:
        return "TRAILING_STOP"
    return None


def _apply_confirm2_evaluation(
    *,
    row: UpbitMaExitForwardShadowEntity,
    state: dict[str, Any],
    event_time: datetime,
    short_ma: Decimal | None,
    long_ma: Decimal | None,
    prev_short: Decimal | None,
    prev_long: Decimal | None,
    thresholds: MaExitThresholds,
    sep_override: float | None = None,
) -> bool:
    """한 evaluator tick = 1 evaluation.

    연속 DEAD_CROSS evaluation: bearish + separation confirmed 상태가
    연속 2회 evaluator 평가에 유지되면 shadow exit.
    """

    if short_ma is None or long_ma is None:
        return False

    hold_ok = is_min_holding_satisfied(
        opened_at=row.entry_at,
        min_holding_seconds=thresholds.ma_exit_min_holding_seconds,
        now=event_time,
    )
    sep_pct = float(
        sep_override if sep_override is not None else thresholds.exit_min_ma_separation_pct
    )
    still_bearish = short_ma < long_ma
    sep_ok = is_dead_cross_confirmed(
        short_ma=short_ma,
        long_ma=long_ma,
        exit_min_ma_separation_pct=sep_pct,
    )

    # 첫 raw dead cross 시각 기록 (telemetry)
    raw_dead = (
        prev_short is not None
        and prev_long is not None
        and prev_short >= prev_long
        and short_ma < long_ma
    )
    if raw_dead and row.shadow_first_dead_cross_at is None:
        row.shadow_first_dead_cross_at = _as_utc(event_time)

    if still_bearish and sep_ok and hold_ok:
        streak = int(state.get("confirm_streak") or 0) + 1
        state["confirm_streak"] = streak
        row.shadow_confirmation_count = streak
    elif short_ma >= long_ma:
        state["confirm_streak"] = 0
        row.shadow_first_dead_cross_at = None
        row.shadow_confirmation_count = 0

    streak_now = int(state.get("confirm_streak") or 0)
    return bool(still_bearish and sep_ok and hold_ok and streak_now >= CONFIRM_EVALUATIONS)


def observe_tick(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    event_time: datetime,
    price: Decimal,
    short_ma: Decimal | None,
    long_ma: Decimal | None,
    prev_short_ma: Decimal | None,
    prev_long_ma: Decimal | None,
    thresholds: MaExitThresholds,
    stop_loss_ratio: Decimal,
    take_profit_ratio: Decimal,
    trail_distance_ratio: Decimal,
    real_signal_reason: str | None = None,
    real_signal_price: Decimal | None = None,
    binding_id: int | None = None,
    settings: Any | None = None,
) -> dict[str, Any]:
    """Realtime tick — no lookahead, REAL emit과 병행."""

    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}

    row = _find_trackable_row(
        session,
        user_broker_account_id=user_broker_account_id,
        symbol=symbol,
        binding_id=binding_id,
    )
    if row is None or row.status == STATUS_PRE_EXISTING_EXCLUDED:
        return {"ok": False, "reason": "NO_ROW"}

    at = _as_utc(event_time) or _utc_now()
    state = _load_state(row)
    out: dict[str, Any] = {"ok": True, "shadow_row_id": int(row.shadow_row_id)}

    # REAL baseline — MA 또는 보호 exit 신호 직후
    if real_signal_reason:
        reason = str(real_signal_reason).upper()
        exit_px = real_signal_price or price
        _record_baseline(
            row,
            exit_reason=reason,
            exit_at=at,
            exit_price=exit_px,
        )
        if row.status == STATUS_ACTIVE and reason == "MA_DEAD_CROSS":
            row.status = STATUS_SHADOW_TRACKING
            out["baseline_recorded"] = reason
            out["continuing_shadow"] = True

        if is_protective_exit_reason(reason):
            # Shadow도 동일 tick 즉시 종료 (delay 금지)
            _complete_shadow(
                row,
                exit_reason=reason,
                exit_at=at,
                exit_price=exit_px,
            )
            _save_state(row, state)
            session.flush()
            return {**out, "shadow_exit": reason, "protective_immediate": True}

    # Shadow 아직 미종료 — protective + confirm2 평가
    if row.shadow_exit_at is None:
        prot = _check_protective_exit(
            row=row,
            price=price,
            event_time=at,
            stop_loss_ratio=stop_loss_ratio,
            take_profit_ratio=take_profit_ratio,
            trail_distance_ratio=trail_distance_ratio,
            state=state,
        )
        if prot:
            prot_px = price
            if prot == "STOP_LOSS":
                prot_px = row.entry_price * (ONE - stop_loss_ratio)
            elif prot == "TAKE_PROFIT":
                prot_px = row.entry_price * (ONE + take_profit_ratio)
            _complete_shadow(row, exit_reason=prot, exit_at=at, exit_price=prot_px)
            _save_state(row, state)
            session.flush()
            return {**out, "shadow_exit": prot}

        if _apply_confirm2_evaluation(
            row=row,
            state=state,
            event_time=at,
            short_ma=short_ma,
            long_ma=long_ma,
            prev_short=prev_short_ma,
            prev_long=prev_long_ma,
            thresholds=thresholds,
        ):
            delayed = (
                row.baseline_exit_at is not None
                and row.baseline_exit_reason == "MA_DEAD_CROSS"
                and row.shadow_net_pnl is None
            )
            _complete_shadow(
                row,
                exit_reason="MA_DEAD_CROSS",
                exit_at=at,
                exit_price=price,
                delayed_loss=bool(
                    delayed
                    and row.baseline_net_pnl is not None
                    and row.shadow_net_pnl is not None
                    and row.shadow_net_pnl < row.baseline_net_pnl
                ),
            )

        # Secondary A — separation 0.30 parallel track
        sec = dict(row.secondary_shadow_json or {})
        sec_a = dict(sec.get(SECONDARY_A_RULE) or {})
        if sec_a.get("exit_at") is None:
            a_streak = int(sec_a.get("confirm_streak") or 0)
            if (
                short_ma is not None
                and long_ma is not None
                and prev_short_ma is not None
                and prev_long_ma is not None
            ):
                raw = prev_short_ma >= prev_long_ma and short_ma < long_ma
                hold_ok = is_min_holding_satisfied(
                    opened_at=row.entry_at,
                    min_holding_seconds=thresholds.ma_exit_min_holding_seconds,
                    now=at,
                )
                sep_ok = is_dead_cross_confirmed(
                    short_ma=short_ma,
                    long_ma=long_ma,
                    exit_min_ma_separation_pct=SECONDARY_A_SEP_PCT,
                )
                if raw and sep_ok and hold_ok:
                    a_streak += 1
                    if sec_a.get("first_dead_cross_at") is None:
                        sec_a["first_dead_cross_at"] = at.isoformat()
                elif short_ma >= long_ma:
                    a_streak = 0
                    sec_a["first_dead_cross_at"] = None
                sec_a["confirm_streak"] = a_streak
                if raw and sep_ok and hold_ok and a_streak >= CONFIRM_EVALUATIONS:
                    pnl = compute_round_trip_pnl(
                        entry_price=row.entry_price,
                        exit_price=price,
                        quantity=row.entry_quantity or ONE,
                        buy_fee=row.entry_fee,
                    )
                    sec_a["exit_at"] = at.isoformat()
                    sec_a["exit_price"] = str(price)
                    sec_a["exit_reason"] = "MA_DEAD_CROSS"
                    sec_a["net_pnl"] = pnl["net_pnl"]
            sec[SECONDARY_A_RULE] = sec_a
            row.secondary_shadow_json = sec

    _save_state(row, state)
    session.flush()
    return out


def finalize_baseline_on_binding_close(
    session: Session,
    *,
    binding_id: int,
    exit_reason: str | None = None,
    exit_at: datetime | None = None,
    exit_price: Decimal | None = None,
    gross_pnl: float | None = None,
    fee: float | None = None,
    net_pnl: float | None = None,
) -> dict[str, Any]:
    """Binding close 시 baseline 보강 — REAL fill 기준."""

    row = session.scalar(
        select(UpbitMaExitForwardShadowEntity).where(
            UpbitMaExitForwardShadowEntity.binding_id == int(binding_id)
        )
    )
    if row is None:
        return {"ok": False, "reason": "NO_ROW"}
    if row.baseline_exit_at is not None:
        return {"ok": True, "already_recorded": True}

    if exit_price is None or exit_at is None:
        return {"ok": False, "reason": "MISSING_EXIT"}

    _record_baseline(
        row,
        exit_reason=str(exit_reason or "UNKNOWN"),
        exit_at=exit_at,
        exit_price=exit_price,
        gross_pnl=gross_pnl,
        fee=fee,
        net_pnl=net_pnl,
    )
    if row.shadow_exit_at is None and row.status == STATUS_ACTIVE:
        row.status = STATUS_SHADOW_TRACKING
    if row.shadow_exit_at is not None and row.difference_net is None:
        if row.baseline_net_pnl is not None and row.shadow_net_pnl is not None:
            row.difference_net = row.shadow_net_pnl - row.baseline_net_pnl
    session.flush()
    return {"ok": True, "shadow_row_id": int(row.shadow_row_id)}


def advance_shadow_tracking_bar(
    session: Session,
    row: UpbitMaExitForwardShadowEntity,
    *,
    bar_close: Decimal,
    bar_at: datetime,
    short_ma: Decimal | None,
    long_ma: Decimal | None,
    prev_short: Decimal | None,
    prev_long: Decimal | None,
    thresholds: MaExitThresholds,
    stop_loss_ratio: Decimal,
    take_profit_ratio: Decimal,
    trail_distance_ratio: Decimal,
) -> dict[str, Any]:
    """REAL 종료 후 SHADOW_TRACKING — 완성 1m bar만 사용 (no lookahead)."""

    if row.status != STATUS_SHADOW_TRACKING or row.shadow_exit_at is not None:
        return {"ok": False, "reason": "NOT_TRACKING"}

    return observe_tick(
        session,
        user_broker_account_id=int(row.user_broker_account_id),
        symbol=row.symbol,
        event_time=bar_at,
        price=bar_close,
        short_ma=short_ma,
        long_ma=long_ma,
        prev_short_ma=prev_short,
        prev_long_ma=prev_long,
        thresholds=thresholds,
        stop_loss_ratio=stop_loss_ratio,
        take_profit_ratio=take_profit_ratio,
        trail_distance_ratio=trail_distance_ratio,
    )


def is_early_dump(exit_at: datetime | None, entry_at: datetime) -> bool:
    if exit_at is None:
        return False
    sec = (_as_utc(exit_at) - _as_utc(entry_at)).total_seconds()  # type: ignore[operator]
    return sec < EARLY_DUMP_SECONDS and sec >= 0
