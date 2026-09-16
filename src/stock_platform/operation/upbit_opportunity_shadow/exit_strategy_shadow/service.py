"""Exit strategy shadow core — enroll / observe / finalize (REAL mutation 0)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.constants import (
    FAMILY_BASELINE_MA,
    FAMILY_STOP_LOSS,
    FAMILY_TAKE_PROFIT,
    FAMILY_TIME_EXIT,
    FAMILY_TRAILING,
    FEE_TAKER_RATE,
    MA_EXIT_MIN_HOLDING_SECONDS,
    MA_EXIT_MIN_SEPARATION_PCT,
    RULE_VERSION,
    SAMPLE_NATURAL_AUTO,
    SAMPLE_TEST,
    SLIPPAGE_BPS_EACH_SIDE,
    STATUS_ACTIVE,
    STATUS_INVALID,
    STATUS_MATURED,
    STATUS_TRIGGERED,
    _TEST_TAGS,
    variant_grid,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.entities import (
    UpbitExitStrategyShadowEntity,
)
from stock_platform.operation.upbit_short_term_turnover.metrics import (
    apply_round_trip_costs,
)
from stock_platform.realtime.ma_exit_policy import is_dead_cross_confirmed

ZERO = Decimal("0")
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
        getattr(settings, "upbit_exit_strategy_shadow_enabled", True)
    )


def resolve_sample_class(metadata: dict[str, Any] | None) -> str:
    """NATURAL_AUTO vs TEST — promotion N에서 TEST 제외."""

    meta = metadata if isinstance(metadata, dict) else {}
    source = str(meta.get("order_source") or "AUTO").upper()
    if source == "MANUAL":
        return "MANUAL"
    tag = str(
        meta.get("test_tag")
        or meta.get("smoke_tag")
        or meta.get("wrk_tag")
        or meta.get("tag")
        or ""
    ).upper()
    for t in _TEST_TAGS:
        if t in tag:
            return SAMPLE_TEST
    if str(meta.get("sample_class") or "").upper() == SAMPLE_TEST:
        return SAMPLE_TEST
    return SAMPLE_NATURAL_AUTO


def enroll_on_natural_entry(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    entry_order_id: int,
    entry_at: datetime,
    entry_price: Decimal,
    entry_qty: Decimal | None = None,
    entry_fee: Decimal | None = None,
    binding_id: int | None = None,
    strategy_id: int | None = None,
    deployment_id: int | None = None,
    broker_order_uuid: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Natural AUTO BUY → variant rows. 중복 entry_order_id면 skip."""

    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    uba = int(user_broker_account_id)
    oid = int(entry_order_id)
    px = Decimal(str(entry_price))
    if px <= ZERO:
        return {"ok": False, "reason": "INVALID_ENTRY_PRICE"}

    existing = session.scalar(
        select(UpbitExitStrategyShadowEntity.shadow_id).where(
            UpbitExitStrategyShadowEntity.entry_order_id == oid
        ).limit(1)
    )
    if existing is not None:
        return {"ok": True, "reason": "ALREADY_ENROLLED", "entry_order_id": oid}

    sample_class = resolve_sample_class(metadata)
    # TEST/MANUAL도 row는 만들되 sample_class로 valid N 제외
    qty = Decimal(str(entry_qty)) if entry_qty is not None else None
    notional = (px * qty) if qty is not None and qty > ZERO else None
    fee = Decimal(str(entry_fee)) if entry_fee is not None else None
    entry_moment = _as_utc(entry_at) or _utc_now()
    provenance = {
        "order_source": "AUTO",
        "enrolled_by": "exit_strategy_shadow_v1",
        "binding_id": binding_id,
    }
    if isinstance(metadata, dict):
        provenance["meta_keys"] = sorted(list(metadata.keys()))[:20]

    created = 0
    for spec in variant_grid():
        row = UpbitExitStrategyShadowEntity(
            user_broker_account_id=uba,
            strategy_id=strategy_id,
            deployment_id=deployment_id,
            binding_id=binding_id,
            symbol=str(symbol).upper(),
            entry_order_id=oid,
            broker_order_uuid=broker_order_uuid,
            entry_at=entry_moment,
            entry_price=px,
            entry_qty=qty,
            entry_notional=notional,
            entry_fee=fee,
            strategy_family=spec["strategy_family"],
            variant_code=spec["variant_code"],
            threshold_value=spec["threshold_value"],
            time_horizon_minutes=spec["time_horizon_minutes"],
            status=STATUS_ACTIVE,
            peak_price=px,
            peak_at=entry_moment,
            mfe_pct=ZERO,
            mae_pct=ZERO,
            sample_class=sample_class,
            provenance=provenance,
            state_json={"peak_restored": True},
            research_only=True,
            rule_version=RULE_VERSION,
        )
        session.add(row)
        created += 1
    session.flush()
    return {
        "ok": True,
        "entry_order_id": oid,
        "variants_created": created,
        "sample_class": sample_class,
    }


def _apply_trigger(
    row: UpbitExitStrategyShadowEntity,
    *,
    price: Decimal,
    at: datetime,
) -> None:
    entry_px = Decimal(str(row.entry_price))
    qty = Decimal(str(row.entry_qty or 0))
    notional = Decimal(str(row.entry_notional or 0))
    if notional <= ZERO and qty > ZERO:
        notional = entry_px * qty
    if notional <= ZERO:
        notional = entry_px  # unit notional fallback

    actual_buy_fee = (
        Decimal(str(row.entry_fee))
        if row.entry_fee is not None
        else None
    )
    costs = apply_round_trip_costs(
        entry_price=entry_px,
        exit_price=price,
        notional_krw=notional,
        fee_rate=FEE_TAKER_RATE,
        slippage_bps_each_side=SLIPPAGE_BPS_EACH_SIDE,
    )
    buy_fee = actual_buy_fee if actual_buy_fee is not None else costs.buy_fee
    # 실제 buy fee 사용 시 sell/slip만 research rate
    sell_fee = costs.sell_fee
    slip = costs.slippage
    gross = costs.gross_pnl
    if actual_buy_fee is not None:
        sell_notional = price * (notional / entry_px if entry_px > ZERO else ZERO)
        gross = sell_notional - notional
        net = gross - buy_fee - sell_fee - slip
    else:
        net = costs.net_pnl

    entry_at = _as_utc(row.entry_at) or at
    hold = max(0, int((at - entry_at).total_seconds()))
    row.trigger_at = at
    row.trigger_price = price
    row.gross_pnl = gross.quantize(Decimal("0.0001"))
    row.buy_fee = buy_fee.quantize(Decimal("0.0001"))
    row.sell_fee = sell_fee.quantize(Decimal("0.0001"))
    row.slippage = slip.quantize(Decimal("0.0001"))
    row.net_pnl = net.quantize(Decimal("0.0001"))
    row.hold_seconds = hold
    row.status = STATUS_TRIGGERED


def observe_price_for_entry(
    session: Session,
    *,
    entry_order_id: int,
    price: Decimal,
    observed_at: datetime | None = None,
    short_ma: Decimal | None = None,
    long_ma: Decimal | None = None,
) -> dict[str, Any]:
    """ACTIVE variants for one entry — trigger 시 REAL 주문 없음."""

    oid = int(entry_order_id)
    px = Decimal(str(price))
    if px <= ZERO:
        return {"ok": False, "reason": "INVALID_PRICE"}
    now = _as_utc(observed_at) or _utc_now()
    rows = list(
        session.scalars(
            select(UpbitExitStrategyShadowEntity).where(
                UpbitExitStrategyShadowEntity.entry_order_id == oid,
                UpbitExitStrategyShadowEntity.status == STATUS_ACTIVE,
            )
        )
    )
    triggered = 0
    for row in rows:
        entry_px = Decimal(str(row.entry_price))
        ret_pct = float((px - entry_px) / entry_px * HUNDRED) if entry_px > ZERO else 0.0

        # MFE / MAE / peak (restart-durable columns)
        peak = Decimal(str(row.peak_price or entry_px))
        if px > peak:
            peak = px
            row.peak_price = peak
            row.peak_at = now
        mfe = float((peak - entry_px) / entry_px * HUNDRED) if entry_px > ZERO else 0.0
        mae = min(float(row.mae_pct or 0), ret_pct)
        if ret_pct < float(row.mae_pct or 0):
            mae = ret_pct
        row.mfe_pct = Decimal(str(round(mfe, 6)))
        row.mae_pct = Decimal(str(round(mae, 6)))

        family = str(row.strategy_family)
        fired = False
        if family == FAMILY_STOP_LOSS and row.threshold_value is not None:
            if ret_pct <= float(row.threshold_value):
                fired = True
        elif family == FAMILY_TAKE_PROFIT and row.threshold_value is not None:
            if ret_pct >= float(row.threshold_value):
                fired = True
        elif family == FAMILY_TRAILING and row.threshold_value is not None:
            if peak > ZERO:
                dd = float((px / peak - 1) * HUNDRED)
                if dd <= -abs(float(row.threshold_value)):
                    # peak 상승 후에만 (peak > entry)
                    if peak > entry_px:
                        fired = True
        elif family == FAMILY_TIME_EXIT and row.time_horizon_minutes:
            entry_at = _as_utc(row.entry_at) or now
            elapsed_min = (now - entry_at).total_seconds() / 60.0
            if elapsed_min >= float(row.time_horizon_minutes):
                fired = True
        elif family == FAMILY_BASELINE_MA:
            entry_at = _as_utc(row.entry_at) or now
            held = (now - entry_at).total_seconds()
            if held >= MA_EXIT_MIN_HOLDING_SECONDS and is_dead_cross_confirmed(
                short_ma=short_ma,
                long_ma=long_ma,
                exit_min_ma_separation_pct=MA_EXIT_MIN_SEPARATION_PCT,
            ):
                fired = True

        if fired:
            _apply_trigger(row, price=px, at=now)
            triggered += 1

    return {"ok": True, "active": len(rows), "triggered": triggered}


def finalize_actual_exit(
    session: Session,
    *,
    entry_order_id: int | None = None,
    binding_id: int | None = None,
    exit_reason: str | None,
    exit_at: datetime | None,
    exit_price: Decimal | None,
    exit_order_id: int | None = None,
    actual_net_pnl: Decimal | None = None,
) -> dict[str, Any]:
    """REAL exit linkage — Shadow는 observation only, REAL 정책 불변."""

    q = select(UpbitExitStrategyShadowEntity)
    if entry_order_id is not None:
        q = q.where(
            UpbitExitStrategyShadowEntity.entry_order_id == int(entry_order_id)
        )
    elif binding_id is not None:
        q = q.where(
            UpbitExitStrategyShadowEntity.binding_id == int(binding_id)
        )
    else:
        return {"ok": False, "reason": "NO_KEY"}

    rows = list(session.scalars(q))
    if not rows:
        return {"ok": True, "updated": 0}

    at = _as_utc(exit_at) or _utc_now()
    px = Decimal(str(exit_price)) if exit_price is not None else None
    updated = 0
    for row in rows:
        row.actual_exit_reason = str(exit_reason or "")[:64] or None
        row.actual_exit_at = at
        row.actual_exit_order_id = exit_order_id
        if px is not None:
            row.actual_exit_price = px
        if actual_net_pnl is not None:
            row.actual_net_pnl = Decimal(str(actual_net_pnl))

        # BASELINE_MA가 아직 ACTIVE면 REAL MA exit를 baseline trigger로 동기화
        if (
            row.status == STATUS_ACTIVE
            and row.strategy_family == FAMILY_BASELINE_MA
            and px is not None
            and str(exit_reason or "").upper() in {
                "MA_DEAD_CROSS",
                "PORTFOLIO_MA_DEAD_CROSS",
                "DEAD_CROSS",
            }
        ):
            _apply_trigger(row, price=px, at=at)

        # 나머지 ACTIVE는 CENSORED(실포지션 종료로 path 단절) — 표본 유지
        if row.status == STATUS_ACTIVE:
            row.status = "CENSORED"
            st = dict(row.state_json or {})
            st["censored_reason"] = "REAL_POSITION_CLOSED"
            row.state_json = st
        elif row.status == STATUS_TRIGGERED:
            row.status = STATUS_MATURED
        updated += 1
    session.flush()
    return {"ok": True, "updated": updated}


def mark_invalid(
    session: Session,
    *,
    entry_order_id: int,
    reason: str,
) -> int:
    rows = list(
        session.scalars(
            select(UpbitExitStrategyShadowEntity).where(
                UpbitExitStrategyShadowEntity.entry_order_id
                == int(entry_order_id),
                UpbitExitStrategyShadowEntity.status == STATUS_ACTIVE,
            )
        )
    )
    for row in rows:
        row.status = STATUS_INVALID
        st = dict(row.state_json or {})
        st["invalid_reason"] = reason[:80]
        row.state_json = st
    return len(rows)
