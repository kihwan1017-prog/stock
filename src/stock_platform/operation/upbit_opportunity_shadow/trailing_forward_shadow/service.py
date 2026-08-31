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
    EARLY_REVIEW_N,
    HISTORICAL_TRAILING_REPLAY_AVAILABLE,
    LAB_COMPARE_VARIANTS,
    LAB_ID,
    POLICY_TRAILING_1P0_1P0_MIN60_V1,
    POLICY_TRAILING_MIN_HOLD_120S_V1,
    POLICY_TRAILING_MIN_HOLD_30S_V1,
    POLICY_TRAILING_MIN_HOLD_60S_V1,
    PROMOTION_REVIEW_N,
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
    T5_ACTIVATION_PCT,
    T5_MIN_HOLDING_SECONDS,
    T5_TRAIL_PCT,
    T6_ACTIVATION_PCT,
    T6_MIN_HOLDING_SECONDS,
    T6_TRAIL_PCT,
    T7_ACTIVATION_PCT,
    T7_MIN_HOLDING_SECONDS,
    T7_TRAIL_PCT,
    T8_ACTIVATION_PCT,
    T8_MIN_HOLDING_SECONDS,
    T8_TRAIL_PCT,
    VARIANT_T0,
    VARIANT_T1,
    VARIANT_T2,
    VARIANT_T3,
    VARIANT_T4,
    VARIANT_T5,
    VARIANT_T6,
    VARIANT_T7,
    VARIANT_T8,
    VARIANT_TRAILING_MIN_HOLD_60S_V1,
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


def deployment_epoch(
    settings: Any | None = None,
    session: Any | None = None,
) -> datetime:
    """고정 deploy epoch — enroll 호출 시 now() 금지.

    우선순위:
    1) settings.upbit_trailing_forward_shadow_deployed_at
    2) DB operation.research_feature_epoch (get-or-create seed)
    3) FEATURE_DEPLOY_EPOCH 상수 (5519e85)
    """

    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.constants import (
        FEATURE_DEPLOY_EPOCH,
        FEATURE_DEPLOY_EPOCH_SOURCE,
        FEATURE_KEY,
    )

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

    if session is not None:
        try:
            from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.epoch import (
                get_or_create_feature_epoch,
            )

            epoch, _src = get_or_create_feature_epoch(
                session,
                feature_key=FEATURE_KEY,
                seed_epoch=FEATURE_DEPLOY_EPOCH,
                seed_source=FEATURE_DEPLOY_EPOCH_SOURCE,
            )
            return _as_utc(epoch) or FEATURE_DEPLOY_EPOCH
        except Exception:  # noqa: BLE001
            pass
    return FEATURE_DEPLOY_EPOCH


def deployment_epoch_meta(
    settings: Any | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """보고서용 source/epoch."""

    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.constants import (
        FEATURE_DEPLOY_EPOCH,
        FEATURE_DEPLOY_EPOCH_SOURCE,
        FEATURE_KEY,
    )

    settings = settings or get_settings()
    raw = str(
        getattr(settings, "upbit_trailing_forward_shadow_deployed_at", "")
        or ""
    ).strip()
    if raw:
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            epoch = datetime.fromisoformat(raw).astimezone(timezone.utc)
            return {
                "SHADOW_DEPLOY_EPOCH": epoch.isoformat(),
                "SHADOW_DEPLOY_EPOCH_SOURCE": "settings.upbit_trailing_forward_shadow_deployed_at",
                "IMMUTABLE": True,
                "RESTART_SAFE": True,
            }
        except ValueError:
            pass
    if session is not None:
        try:
            from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.epoch import (
                get_or_create_feature_epoch,
            )

            epoch, src = get_or_create_feature_epoch(
                session,
                feature_key=FEATURE_KEY,
                seed_epoch=FEATURE_DEPLOY_EPOCH,
                seed_source=FEATURE_DEPLOY_EPOCH_SOURCE,
            )
            return {
                "SHADOW_DEPLOY_EPOCH": (_as_utc(epoch) or FEATURE_DEPLOY_EPOCH).isoformat(),
                "SHADOW_DEPLOY_EPOCH_SOURCE": f"db:{src}",
                "IMMUTABLE": True,
                "RESTART_SAFE": True,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "SHADOW_DEPLOY_EPOCH": FEATURE_DEPLOY_EPOCH.isoformat(),
                "SHADOW_DEPLOY_EPOCH_SOURCE": FEATURE_DEPLOY_EPOCH_SOURCE,
                "IMMUTABLE": True,
                "RESTART_SAFE": True,
                "db_fallback_error": type(exc).__name__,
            }
    return {
        "SHADOW_DEPLOY_EPOCH": FEATURE_DEPLOY_EPOCH.isoformat(),
        "SHADOW_DEPLOY_EPOCH_SOURCE": FEATURE_DEPLOY_EPOCH_SOURCE,
        "IMMUTABLE": True,
        "RESTART_SAFE": True,
    }


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
        VARIANT_T5: {
            "activation_pct": T5_ACTIVATION_PCT,
            "trail_pct": T5_TRAIL_PCT,
            "min_holding_seconds": T5_MIN_HOLDING_SECONDS,
            "label": POLICY_TRAILING_MIN_HOLD_60S_V1,
            "policy_id": POLICY_TRAILING_MIN_HOLD_60S_V1,
            # REAL arm +1.0% / drawdown -0.8% 와 동일 + min_hold only
            "mirrors_real_trailing": True,
        },
        VARIANT_T6: {
            "activation_pct": T6_ACTIVATION_PCT,
            "trail_pct": T6_TRAIL_PCT,
            "min_holding_seconds": T6_MIN_HOLDING_SECONDS,
            "label": POLICY_TRAILING_MIN_HOLD_30S_V1,
            "policy_id": POLICY_TRAILING_MIN_HOLD_30S_V1,
            "mirrors_real_trailing": True,
        },
        VARIANT_T7: {
            "activation_pct": T7_ACTIVATION_PCT,
            "trail_pct": T7_TRAIL_PCT,
            "min_holding_seconds": T7_MIN_HOLDING_SECONDS,
            "label": POLICY_TRAILING_MIN_HOLD_120S_V1,
            "policy_id": POLICY_TRAILING_MIN_HOLD_120S_V1,
            "mirrors_real_trailing": True,
        },
        VARIANT_T8: {
            "activation_pct": T8_ACTIVATION_PCT,
            "trail_pct": T8_TRAIL_PCT,
            "min_holding_seconds": T8_MIN_HOLDING_SECONDS,
            "label": POLICY_TRAILING_1P0_1P0_MIN60_V1,
            "policy_id": POLICY_TRAILING_1P0_1P0_MIN60_V1,
            "mirrors_real_trailing": False,
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
        "early_trigger_seen": False,
        "early_trigger_at": None,
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

    deploy = deployment_epoch(settings, session=session)
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
            "lab_id": LAB_ID,
            "real_order_from_shadow": 0,
            "historical_replay_available": HISTORICAL_TRAILING_REPLAY_AVAILABLE,
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
        # forward-only: 기존 row에 없던 신규 variant(T5 등)는 주입하지 않음
        if key not in variants:
            continue
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
        if v.get("armed_at") and v.get("trigger_at") is None:
            trig = _trigger_price(peak, float(spec["trail_pct"]))
            would_trigger = price <= trig
            if would_trigger and hold_s < min_hold:
                # 60초 전 조건 충족 → EARLY_TRIGGER_SEEN (강제 exit 금지)
                v["early_trigger_seen"] = True
                if not v.get("early_trigger_at"):
                    v["early_trigger_at"] = now.isoformat()
            elif would_trigger and hold_s >= min_hold:
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
    entry_order_id: int | None = None,
    resolve_ledger: bool = True,
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

    # Canonical ledger baseline — upbit binding_id ≠ risk binding_id
    reconciled = False
    if resolve_ledger and (
        net_pnl is None or fee is None or gross_pnl is None or exit_price is None
    ):
        from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.baseline import (
            resolve_baseline_outcome_for_entry,
        )

        oid = entry_order_id if entry_order_id is not None else row.entry_order_id
        resolved = resolve_baseline_outcome_for_entry(
            session,
            entry_order_id=int(oid) if oid is not None else None,
            user_broker_account_id=int(row.user_broker_account_id),
            fallback_exit_reason=exit_reason,
            fallback_exit_at=exit_at,
            fallback_exit_price=exit_price,
        )
        if resolved and resolved.get("ok"):
            if gross_pnl is None:
                gross_pnl = float(resolved["gross_pnl"])
            if fee is None:
                fee = float(resolved["fee"])
            if net_pnl is None:
                net_pnl = float(resolved["net_pnl"])
            if exit_price is None and resolved.get("exit_price") is not None:
                exit_price = Decimal(str(resolved["exit_price"]))
            if not exit_reason or exit_reason == "UNKNOWN":
                exit_reason = str(resolved.get("exit_reason") or exit_reason)
            if exit_at is None and resolved.get("exit_at_dt") is not None:
                exit_at = resolved["exit_at_dt"]
            reconciled = True

    already_completed = row.status == STATUS_COMPLETED
    if already_completed and row.baseline_net_pnl is not None and not reconciled:
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

    variants = dict(row.variants_json or {})
    t0 = dict(variants.get(VARIANT_T0) or {})
    if t0.get("outcome_status") in (None, "ACTIVE") and exit_price is not None:
        t0["trigger_at"] = (row.baseline_exit_at or _utc_now()).isoformat()
        t0["virtual_exit_price"] = str(exit_price)
        t0["outcome_status"] = f"BASELINE_{row.baseline_exit_reason}"
        if net_pnl is not None:
            t0["net"] = float(net_pnl)
        if gross_pnl is not None:
            t0["gross"] = float(gross_pnl)
        if fee is not None:
            t0["estimated_fee"] = float(fee)
        entry_at = _as_utc(row.entry_at)
        if entry_at and row.baseline_exit_at:
            t0["holding_seconds"] = max(
                0.0, (row.baseline_exit_at - entry_at).total_seconds()
            )
        variants[VARIANT_T0] = t0

    # REAL terminal boundary — ACTIVE shadow variants close at REAL exit (미래가격 금지)
    if exit_price is not None:
        qty = Decimal(str(row.entry_quantity or ZERO))
        if qty <= ZERO:
            qty = ONE
        entry = Decimal(str(row.entry_price))
        for key, vraw in list(variants.items()):
            if key == VARIANT_T0:
                continue
            v = dict(vraw or {})
            if v.get("outcome_status") not in (None, "ACTIVE"):
                variants[key] = v
                continue
            v["trigger_at"] = (row.baseline_exit_at or _utc_now()).isoformat()
            v["virtual_exit_price"] = str(exit_price)
            v["outcome_status"] = "REAL_TERMINAL_BOUNDARY"
            pnl = compute_round_trip_pnl(
                entry_price=entry,
                exit_price=exit_price,
                quantity=qty,
                buy_fee=row.entry_fee,
            )
            v["gross"] = pnl["gross_pnl"]
            v["estimated_fee"] = pnl["fee"]
            v["net"] = pnl["net_pnl"]
            entry_at = _as_utc(row.entry_at)
            if entry_at and row.baseline_exit_at:
                v["holding_seconds"] = max(
                    0.0, (row.baseline_exit_at - entry_at).total_seconds()
                )
            variants[key] = v

    row.variants_json = variants
    state = dict(row.shadow_state_json or {})
    if reconciled:
        state["RECONCILED_EXISTING_FORWARD"] = True
        state["baseline_source"] = "binding_closed_trade_metrics"
    row.shadow_state_json = state
    row.status = STATUS_COMPLETED
    if row.completed_at is None:
        row.completed_at = _utc_now()
    session.flush()
    return {
        "ok": True,
        "shadow_row_id": int(row.shadow_row_id),
        "reconciled_ledger": reconciled,
        "baseline_net_pnl": float(row.baseline_net_pnl)
        if row.baseline_net_pnl is not None
        else None,
    }


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
    # promotion 기본: VALID only (INVALID quarantine 제외, raw 유지)
    completed_valid = [
        r
        for r in completed
        if bool(getattr(r, "included_in_research_metrics", True))
        and str(getattr(r, "data_quality_status", "UNKNOWN") or "UNKNOWN").upper()
        != "INVALID"
    ]
    quarantined = [
        r
        for r in rows
        if (not bool(getattr(r, "included_in_research_metrics", True)))
        or str(getattr(r, "data_quality_status", "UNKNOWN") or "UNKNOWN").upper()
        == "INVALID"
    ]
    sample_n = len(completed_valid)
    target = SAMPLE_TARGET_INITIAL
    if sample_n >= SAMPLE_TARGET_NEXT:
        target = SAMPLE_TARGET_PRIMARY
    elif sample_n >= SAMPLE_TARGET_INITIAL:
        target = SAMPLE_TARGET_NEXT

    per_variant: dict[str, Any] = {}
    for key in variant_specs():
        nets: list[float] = []
        exits = 0
        for r in completed_valid:
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

    n10_valid_ready = sample_n >= 10
    return {
        "schema": RULE_VERSION,
        "enabled": shadow_enabled(),
        "SAMPLE_COUNT": sample_n,
        "SAMPLE_COUNT_RAW_COMPLETED": len(completed),
        "ACTIVE_COUNT": len(active),
        "TOTAL_COHORTS": len(rows),
        "VALID_COHORTS": len(
            [
                r
                for r in rows
                if bool(getattr(r, "included_in_research_metrics", True))
                and str(getattr(r, "data_quality_status", "UNKNOWN") or "").upper()
                != "INVALID"
            ]
        ),
        "QUARANTINED": len(quarantined),
        "N10_VALID_READY": n10_valid_ready,
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
        "PROMOTION_SAMPLE_BASIS": "VALID_ONLY",
        "raw_data_deleted": False,
    }


def _pf(wins_sum: float, losses_abs: float) -> float | None:
    if losses_abs <= 0:
        return None if wins_sum <= 0 else None
    return round(wins_sum / losses_abs, 6) if losses_abs > 0 else None


def _mdd_from_series(nets: list[float]) -> float | None:
    if not nets:
        return None
    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for n in nets:
        cum += n
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return round(mdd, 4)


def pair_row_variant(
    row: UpbitTrailingForwardShadowEntity,
    variant_key: str,
) -> dict[str, Any]:
    """Canonical entry×variant comparison unit."""

    specs = variant_specs().get(variant_key) or {}
    v = (row.variants_json or {}).get(variant_key) or {}
    baseline_net = (
        float(row.baseline_net_pnl) if row.baseline_net_pnl is not None else None
    )
    shadow_net = float(v["net"]) if v.get("net") is not None else None
    invalid: list[str] = []
    if not bool(getattr(row, "included_in_research_metrics", True)):
        invalid.append("EXCLUDED_FROM_RESEARCH_METRICS")
    if str(getattr(row, "data_quality_status", "") or "").upper() == "INVALID":
        invalid.append("DATA_QUALITY_INVALID")
    if baseline_net is None:
        invalid.append("BASELINE_NET_NULL")
    if row.baseline_exit_at is None:
        invalid.append("BASELINE_NOT_EXITED")
    if shadow_net is None or v.get("virtual_exit_price") is None:
        invalid.append("SHADOW_OUTCOME_NULL")
    paired_valid = len(invalid) == 0
    delta = (
        round(shadow_net - baseline_net, 4)
        if paired_valid and shadow_net is not None and baseline_net is not None
        else None
    )
    entry_at = _as_utc(row.entry_at)
    baseline_hold = None
    if entry_at and row.baseline_exit_at:
        baseline_hold = max(
            0.0, (_as_utc(row.baseline_exit_at) - entry_at).total_seconds()  # type: ignore[operator]
        )
    return {
        "entry_id": row.entry_order_id,
        "shadow_row_id": int(row.shadow_row_id),
        "binding_id": int(row.binding_id),
        "symbol": row.symbol,
        "entry_at": entry_at.isoformat() if entry_at else None,
        "entry_price": str(row.entry_price),
        "variant": variant_key,
        "arm_pct": specs.get("activation_pct"),
        "drawdown_pct": specs.get("trail_pct"),
        "min_hold_seconds": specs.get("min_holding_seconds"),
        "peak_price": v.get("peak_price"),
        "peak_at": v.get("peak_at"),
        "early_trigger_at": v.get("early_trigger_at"),
        "eligible_at": None,
        "virtual_exit_at": v.get("trigger_at"),
        "virtual_exit_price": v.get("virtual_exit_price"),
        "virtual_exit_reason": v.get("outcome_status"),
        "baseline_exit_at": (
            _as_utc(row.baseline_exit_at).isoformat() if row.baseline_exit_at else None
        ),
        "baseline_exit_price": (
            str(row.baseline_exit_price) if row.baseline_exit_price is not None else None
        ),
        "baseline_exit_reason": row.baseline_exit_reason,
        "baseline_gross": (
            float(row.baseline_gross_pnl) if row.baseline_gross_pnl is not None else None
        ),
        "baseline_fees": float(row.baseline_fee) if row.baseline_fee is not None else None,
        "baseline_net": baseline_net,
        "shadow_gross": v.get("gross"),
        "shadow_fees": v.get("estimated_fee"),
        "shadow_net": shadow_net,
        "delta_net": delta,
        "baseline_hold_seconds": baseline_hold,
        "shadow_hold_seconds": v.get("holding_seconds"),
        "paired_valid": paired_valid,
        "invalid_reason": invalid,
        "RECONCILED_EXISTING_FORWARD": bool(
            (row.shadow_state_json or {}).get("RECONCILED_EXISTING_FORWARD")
        ),
    }


def reconcile_existing_forward_baselines(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """누락 lineage 연결만 — 새 virtual exit / historical backfill 금지."""

    q = select(UpbitTrailingForwardShadowEntity).where(
        UpbitTrailingForwardShadowEntity.status.in_(
            (STATUS_ACTIVE, STATUS_COMPLETED)
        )
    )
    if user_broker_account_id is not None:
        q = q.where(
            UpbitTrailingForwardShadowEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    rows = list(session.scalars(q.order_by(UpbitTrailingForwardShadowEntity.shadow_row_id)))
    scanned = 0
    reconciled = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    for row in rows:
        if scanned >= limit:
            break
        scanned += 1
        if row.baseline_net_pnl is not None and row.status == STATUS_COMPLETED:
            skipped += 1
            continue
        if row.entry_order_id is None:
            skipped += 1
            continue
        try:
            out = finalize_baseline_on_binding_close(
                session,
                binding_id=int(row.binding_id),
                exit_reason=row.baseline_exit_reason,
                exit_at=row.baseline_exit_at,
                exit_price=row.baseline_exit_price,
                entry_order_id=int(row.entry_order_id),
                resolve_ledger=True,
            )
            if out.get("ok") and out.get("baseline_net_pnl") is not None:
                reconciled += 1
                state = dict(row.shadow_state_json or {})
                state["RECONCILED_EXISTING_FORWARD"] = True
                row.shadow_state_json = state
            else:
                skipped += 1
                if not out.get("ok"):
                    errors.append(
                        {
                            "shadow_row_id": int(row.shadow_row_id),
                            "reason": out.get("reason") or out,
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "shadow_row_id": int(row.shadow_row_id),
                    "error": type(exc).__name__,
                }
            )
    session.flush()
    return {
        "ok": True,
        "RECONCILED_EXISTING_FORWARD": True,
        "scanned": scanned,
        "reconciled": reconciled,
        "skipped": skipped,
        "errors": errors[:20],
    }


def summarize_exit_optimization_lab(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
    include_rows: bool = False,
    row_limit: int = 200,
) -> dict[str, Any]:
    """GPT/Admin용 Lab V2 canonical evaluation dataset."""

    q = select(UpbitTrailingForwardShadowEntity)
    if user_broker_account_id is not None:
        q = q.where(
            UpbitTrailingForwardShadowEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    rows = list(session.scalars(q))
    active = [r for r in rows if r.status == STATUS_ACTIVE]
    completed = [r for r in rows if r.status == STATUS_COMPLETED]

    variant_metrics: dict[str, Any] = {}
    all_pair_rows: list[dict[str, Any]] = []
    for key in LAB_COMPARE_VARIANTS:
        pairs = [pair_row_variant(r, key) for r in completed]
        valid = [p for p in pairs if p["paired_valid"]]
        valid_sorted = sorted(
            valid,
            key=lambda p: p.get("entry_at") or "",
        )
        base_nets = [float(p["baseline_net"]) for p in valid_sorted]
        sh_nets = [float(p["shadow_net"]) for p in valid_sorted]
        deltas = [float(p["delta_net"]) for p in valid_sorted]
        base_fees = [
            float(p["baseline_fees"])
            for p in valid_sorted
            if p.get("baseline_fees") is not None
        ]
        sh_fees = [
            float(p["shadow_fees"])
            for p in valid_sorted
            if p.get("shadow_fees") is not None
        ]
        base_holds = [
            float(p["baseline_hold_seconds"])
            for p in valid_sorted
            if p.get("baseline_hold_seconds") is not None
        ]
        sh_holds = [
            float(p["shadow_hold_seconds"])
            for p in valid_sorted
            if p.get("shadow_hold_seconds") is not None
        ]

        def _stats(nets: list[float]) -> dict[str, Any]:
            if not nets:
                return {
                    "net": 0.0,
                    "win_rate": None,
                    "pf": None,
                    "avg": None,
                    "median": None,
                }
            wins = [n for n in nets if n > 0]
            losses = [n for n in nets if n <= 0]
            win_sum = sum(wins)
            loss_abs = abs(sum(losses))
            ordered = sorted(nets)
            mid = len(ordered) // 2
            median = (
                ordered[mid]
                if len(ordered) % 2 == 1
                else (ordered[mid - 1] + ordered[mid]) / 2
            )
            return {
                "net": round(sum(nets), 4),
                "win_rate": round(len(wins) / len(nets), 4),
                "pf": (
                    round(win_sum / loss_abs, 6) if loss_abs > 0 else None
                ),
                "avg": round(sum(nets) / len(nets), 4),
                "median": round(median, 4),
            }

        bs = _stats(base_nets)
        ss = _stats(sh_nets)
        n = len(valid_sorted)
        readiness = "표본 수집 중"
        if n >= PROMOTION_REVIEW_N:
            readiness = "승격 검토 가능"
        elif n >= EARLY_REVIEW_N:
            readiness = "1차 검토 가능"
        variant_metrics[key] = {
            "TOTAL": len(rows),
            "ACTIVE": len(active),
            "COMPLETED": len(completed),
            "VALID_PAIRED_N": n,
            "BASELINE_NET": bs["net"],
            "SHADOW_NET": ss["net"],
            "DELTA_NET": round(sum(deltas), 4) if deltas else 0.0,
            "BASELINE_PF": bs["pf"],
            "SHADOW_PF": ss["pf"],
            "BASELINE_WIN_RATE": bs["win_rate"],
            "SHADOW_WIN_RATE": ss["win_rate"],
            "BASELINE_AVG_HOLD": (
                round(sum(base_holds) / len(base_holds), 2) if base_holds else None
            ),
            "SHADOW_AVG_HOLD": (
                round(sum(sh_holds) / len(sh_holds), 2) if sh_holds else None
            ),
            "BASELINE_MEDIAN_HOLD": (
                round(sorted(base_holds)[len(base_holds) // 2], 2)
                if base_holds
                else None
            ),
            "SHADOW_MEDIAN_HOLD": (
                round(sorted(sh_holds)[len(sh_holds) // 2], 2) if sh_holds else None
            ),
            "BASELINE_FEES": round(sum(base_fees), 4) if base_fees else 0.0,
            "SHADOW_ESTIMATED_FEES": round(sum(sh_fees), 4) if sh_fees else 0.0,
            "AVG_DELTA_PER_TRADE": (
                round(sum(deltas) / len(deltas), 4) if deltas else None
            ),
            "BASELINE_MDD": _mdd_from_series(base_nets),
            "SHADOW_MDD": _mdd_from_series(sh_nets),
            "EARLY_REVIEW_READY": n >= EARLY_REVIEW_N,
            "PROMOTION_REVIEW_READY": n >= PROMOTION_REVIEW_N,
            "readiness_label": readiness,
            "AUTO_PROMOTION": False,
        }
        if include_rows:
            all_pair_rows.extend(valid_sorted[:row_limit])

    t5_n = int(variant_metrics.get(VARIANT_T5, {}).get("VALID_PAIRED_N") or 0)
    return {
        "ok": True,
        "lab_id": LAB_ID,
        "schema": RULE_VERSION,
        "ROOT_CAUSE_T5_N0": (
            "finalize_baseline_on_binding_close called without ledger PnL; "
            "baseline_net_pnl stayed NULL; pairing required baseline_net"
        ),
        "variants": variant_specs(),
        "lab_compare_variants": list(LAB_COMPARE_VARIANTS),
        "per_variant": variant_metrics,
        "EARLY_REVIEW_READY": any(
            v.get("EARLY_REVIEW_READY") for v in variant_metrics.values()
        ),
        "PROMOTION_REVIEW_READY": any(
            v.get("PROMOTION_REVIEW_READY") for v in variant_metrics.values()
        ),
        "T5_VALID_PAIRED_N": t5_n,
        "REAL_TRAILING_UNCHANGED": True,
        "AUTO_PROMOTION_FORBIDDEN": True,
        "rows": all_pair_rows if include_rows else [],
        "TOTAL_ROWS": len(rows),
        "ACTIVE": len(active),
        "COMPLETED": len(completed),
    }
