"""Upbit trailing forward shadow — core service (REAL mutation 0)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.fee_policy import UpbitFeePolicy
from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.constants import (
    HISTORICAL_TRAILING_REPLAY_AVAILABLE,
    RESEARCH_ONLY_LABEL,
    RULE_VERSION,
    SAMPLE_TARGET_INITIAL,
    SAMPLE_TARGET_NEXT,
    SAMPLE_TARGET_PRIMARY,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_PRE_EXISTING_EXCLUDED,
    T0_ACTIVATION_PCT,
    T0_TRAIL_PCT,
    T1_ACTIVATION_PCT,
    T1_TRAIL_PCT,
    T2_ACTIVATION_PCT,
    T2_TRAIL_PCT,
    T3_ACTIVATION_PCT,
    T3_TRAIL_PCT,
    T4_ACTIVATION_PCT,
    T4_MIN_HOLDING_SECONDS,
    T4_TRAIL_PCT,
    VARIANT_T0,
    VARIANT_T1,
    VARIANT_T2,
    VARIANT_T3,
    VARIANT_T4,
)
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.entities import (
    UpbitTrailingForwardShadowEntity,
)

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


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
    return bool(
        getattr(settings, "upbit_trailing_forward_shadow_enabled", True)
    )


def deployment_epoch(settings: Any | None = None) -> datetime:
    settings = settings or get_settings()
    raw = str(
        getattr(settings, "upbit_trailing_forward_shadow_deployed_at", "")
        or ""
    ).strip()
    if raw:
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            return datetime.fromisoformat(raw).astimezone(timezone.utc)
        except ValueError:
            pass
    return _utc_now()


def variant_specs() -> dict[str, dict[str, Any]]:
    return {
        VARIANT_T0: {
            "activation_pct": T0_ACTIVATION_PCT,
            "trail_pct": T0_TRAIL_PCT,
            "min_holding_seconds": 0,
            "label": "CURRENT_REAL",
        },
        VARIANT_T1: {
            "activation_pct": T1_ACTIVATION_PCT,
            "trail_pct": T1_TRAIL_PCT,
            "min_holding_seconds": 0,
            "label": "MIN_ACTIVATION_0.5",
        },
        VARIANT_T2: {
            "activation_pct": T2_ACTIVATION_PCT,
            "trail_pct": T2_TRAIL_PCT,
            "min_holding_seconds": 0,
            "label": "TRAIL_5PCT",
        },
        VARIANT_T3: {
            "activation_pct": T3_ACTIVATION_PCT,
            "trail_pct": T3_TRAIL_PCT,
            "min_holding_seconds": 0,
            "label": "ACT_0.5_TRAIL_5",
        },
        VARIANT_T4: {
            "activation_pct": T4_ACTIVATION_PCT,
            "trail_pct": T4_TRAIL_PCT,
            "min_holding_seconds": T4_MIN_HOLDING_SECONDS,
            "label": "MIN_HOLD_180S",
        },
    }


def _init_variant(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "activation_pct": spec["activation_pct"],
        "trail_pct": spec["trail_pct"],
        "min_holding_seconds": spec["min_holding_seconds"],
        "label": spec["label"],
        "peak_price": None,
        "peak_at": None,
        "armed_at": None,
        "trigger_at": None,
        "virtual_exit_price": None,
        "holding_seconds": None,
        "gross": None,
        "estimated_fee": None,
        "net": None,
        "mfe": None,
        "mae": None,
        "giveback_from_peak": None,
        "outcome_status": "ACTIVE",
    }


def compute_round_trip_pnl(
    *,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
    buy_fee: Decimal | None = None,
    fee_rate: Decimal | None = None,
) -> dict[str, float]:
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
    settings: Any | None = None,
) -> dict[str, Any]:
    """새 REAL OPEN 시 cohort 등록 — backfill 금지, 중복 binding 0."""

    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}

    existing = session.scalar(
        select(UpbitTrailingForwardShadowEntity).where(
            UpbitTrailingForwardShadowEntity.binding_id == int(binding_id)
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

    specs = variant_specs()
    variants = {k: _init_variant(v) for k, v in specs.items()}
    # 시작 peak = entry
    for v in variants.values():
        v["peak_price"] = str(entry_price)

    row = UpbitTrailingForwardShadowEntity(
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=strategy_id,
        symbol=str(symbol).upper(),
        binding_id=int(binding_id),
        entry_order_id=entry_order_id,
        entry_at=opened,
        entry_price=entry_price,
        entry_quantity=entry_quantity,
        entry_fee=entry_fee,
        rule_version=RULE_VERSION,
        status=status,
        research_only=True,
        variants_json=variants,
        shadow_state_json={
            "research_label": RESEARCH_ONLY_LABEL,
            "real_order_from_shadow": 0,
            "historical_replay_available": HISTORICAL_TRAILING_REPLAY_AVAILABLE,
        },
    )
    session.add(row)
    session.flush()
    sid = getattr(row, "shadow_row_id", None)
    return {
        "ok": True,
        "duplicate": False,
        "shadow_row_id": int(sid) if sid is not None else None,
        "status": status,
    }


def _armed(
    *,
    entry: Decimal,
    peak: Decimal,
    activation_pct: float,
) -> bool:
    if peak <= entry:
        return False
    if activation_pct <= 0:
        return True
    gain = (peak - entry) / entry * HUNDRED
    return gain >= Decimal(str(activation_pct))


def _trigger_price(peak: Decimal, trail_pct: float) -> Decimal:
    return peak * (ONE - Decimal(str(trail_pct)) / HUNDRED)


def observe_price_tick(
    session: Session,
    *,
    binding_id: int,
    price: Decimal,
    observed_at: datetime | None = None,
    quantity: Decimal | None = None,
) -> dict[str, Any]:
    """ACTIVE shadow에 대해 T0~T4 가상 trailing 평가 — REAL SELL 0."""

    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    row = session.scalar(
        select(UpbitTrailingForwardShadowEntity).where(
            UpbitTrailingForwardShadowEntity.binding_id == int(binding_id)
        )
    )
    if row is None or row.status != STATUS_ACTIVE:
        return {"ok": False, "reason": "NOT_ACTIVE"}

    now = _as_utc(observed_at) or _utc_now()
    entry = Decimal(str(row.entry_price))
    qty = Decimal(
        str(
            quantity
            if quantity is not None
            else (row.entry_quantity or ZERO)
        )
    )
    if qty <= ZERO:
        qty = ONE  # pnl 스케일만 — 주문 없음
    variants = dict(row.variants_json or {})
    entry_at = _as_utc(row.entry_at) or now
    hold_s = max(0.0, (now - entry_at).total_seconds())
    state = dict(row.shadow_state_json or {})
    mfe = Decimal(str(state.get("mfe") or 0))
    mae = Decimal(str(state.get("mae") or 0))
    gain_now = (price - entry) / entry * HUNDRED if entry > ZERO else ZERO
    mfe = max(mfe, gain_now)
    mae = min(mae, gain_now)
    state["mfe"] = float(mfe)
    state["mae"] = float(mae)

    for key, spec in variant_specs().items():
        v = dict(variants.get(key) or _init_variant(spec))
        if v.get("outcome_status") not in (None, "ACTIVE"):
            variants[key] = v
            continue
        peak = Decimal(str(v.get("peak_price") or entry))
        if price > peak:
            peak = price
            v["peak_price"] = str(peak)
            v["peak_at"] = now.isoformat()
        if v.get("armed_at") is None and _armed(
            entry=entry,
            peak=peak,
            activation_pct=float(spec["activation_pct"]),
        ):
            v["armed_at"] = now.isoformat()
        min_hold = int(spec.get("min_holding_seconds") or 0)
        if (
            v.get("armed_at")
            and v.get("trigger_at") is None
            and hold_s >= min_hold
        ):
            trig = _trigger_price(peak, float(spec["trail_pct"]))
            if price <= trig:
                v["trigger_at"] = now.isoformat()
                v["virtual_exit_price"] = str(price)
                v["holding_seconds"] = hold_s
                pnl = compute_round_trip_pnl(
                    entry_price=entry,
                    exit_price=price,
                    quantity=qty,
                    buy_fee=row.entry_fee,
                )
                v["gross"] = pnl["gross_pnl"]
                v["estimated_fee"] = pnl["fee"]
                v["net"] = pnl["net_pnl"]
                v["mfe"] = float(mfe)
                v["mae"] = float(mae)
                peak_gain = (
                    float((peak - entry) / entry * HUNDRED)
                    if entry > ZERO
                    else 0.0
                )
                exit_gain = float(gain_now)
                v["giveback_from_peak"] = round(peak_gain - exit_gain, 6)
                v["outcome_status"] = "VIRTUAL_TRAILING_EXIT"
        variants[key] = v

    row.variants_json = variants
    row.shadow_state_json = state
    row.context_as_of = now
    session.flush()
    return {"ok": True, "binding_id": int(binding_id)}


def finalize_baseline_on_binding_close(
    session: Session,
    *,
    binding_id: int,
    exit_reason: str | None,
    exit_at: datetime | None,
    exit_price: Decimal | None,
    gross_pnl: float | None = None,
    fee: float | None = None,
    net_pnl: float | None = None,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    row = session.scalar(
        select(UpbitTrailingForwardShadowEntity).where(
            UpbitTrailingForwardShadowEntity.binding_id == int(binding_id)
        )
    )
    if row is None:
        return {"ok": False, "reason": "NOT_FOUND"}
    if row.status == STATUS_COMPLETED:
        return {"ok": True, "duplicate": True}

    row.baseline_exit_reason = str(exit_reason or "UNKNOWN")[:64]
    row.baseline_exit_at = _as_utc(exit_at) or _utc_now()
    if exit_price is not None:
        row.baseline_exit_price = exit_price
    if gross_pnl is not None:
        row.baseline_gross_pnl = Decimal(str(round(gross_pnl, 4)))
    if fee is not None:
        row.baseline_fee = Decimal(str(round(fee, 4)))
    if net_pnl is not None:
        row.baseline_net_pnl = Decimal(str(round(net_pnl, 4)))

    # T0 virtual가 아직이면 REAL exit를 T0 관측으로 기록 (SELL 생성 아님)
    variants = dict(row.variants_json or {})
    t0 = dict(variants.get(VARIANT_T0) or {})
    if t0.get("outcome_status") == "ACTIVE" and exit_price is not None:
        t0["trigger_at"] = (row.baseline_exit_at or _utc_now()).isoformat()
        t0["virtual_exit_price"] = str(exit_price)
        t0["outcome_status"] = f"BASELINE_{row.baseline_exit_reason}"
        if net_pnl is not None:
            t0["net"] = float(net_pnl)
        if gross_pnl is not None:
            t0["gross"] = float(gross_pnl)
        if fee is not None:
            t0["estimated_fee"] = float(fee)
        variants[VARIANT_T0] = t0
        row.variants_json = variants

    row.status = STATUS_COMPLETED
    row.completed_at = _utc_now()
    session.flush()
    return {"ok": True, "shadow_row_id": int(row.shadow_row_id)}


def summarize_cohort(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    q = select(UpbitTrailingForwardShadowEntity)
    if user_broker_account_id is not None:
        q = q.where(
            UpbitTrailingForwardShadowEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    rows = list(session.scalars(q))
    active = [r for r in rows if r.status == STATUS_ACTIVE]
    completed = [r for r in rows if r.status == STATUS_COMPLETED]
    sample_n = len(completed)
    target = SAMPLE_TARGET_INITIAL
    if sample_n >= SAMPLE_TARGET_NEXT:
        target = SAMPLE_TARGET_PRIMARY
    elif sample_n >= SAMPLE_TARGET_INITIAL:
        target = SAMPLE_TARGET_NEXT

    per_variant: dict[str, Any] = {}
    for key in variant_specs():
        nets: list[float] = []
        exits = 0
        for r in completed:
            v = (r.variants_json or {}).get(key) or {}
            if v.get("trigger_at"):
                exits += 1
            if v.get("net") is not None:
                nets.append(float(v["net"]))
        wins = sum(1 for n in nets if n > 0)
        losses = sum(1 for n in nets if n <= 0)
        total_net = sum(nets) if nets else 0.0
        per_variant[key] = {
            "EXIT_COUNT": exits,
            "WIN": wins,
            "LOSS": losses,
            "WIN_RATE": (wins / len(nets)) if nets else None,
            "NET": round(total_net, 4),
            "AVG_NET": round(total_net / len(nets), 4) if nets else None,
            "SAMPLE_WITH_NET": len(nets),
        }

    return {
        "schema": RULE_VERSION,
        "enabled": shadow_enabled(),
        "SAMPLE_COUNT": sample_n,
        "ACTIVE_COUNT": len(active),
        "TARGET": target,
        "TARGETS": {
            "initial": SAMPLE_TARGET_INITIAL,
            "next": SAMPLE_TARGET_NEXT,
            "primary": SAMPLE_TARGET_PRIMARY,
        },
        "REAL_ORDER_FROM_SHADOW": 0,
        "HISTORICAL_TRAILING_REPLAY_AVAILABLE": HISTORICAL_TRAILING_REPLAY_AVAILABLE,
        "variants": variant_specs(),
        "per_variant": per_variant,
        "REAL_POLICY_CHANGED": False,
        "promotion": "AUTO_PROMOTION_FORBIDDEN",
    }
