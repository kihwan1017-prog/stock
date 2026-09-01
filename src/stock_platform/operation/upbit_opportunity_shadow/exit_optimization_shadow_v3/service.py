"""Exit Optimization Shadow Lab V3 — core service (REAL mutation 0)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.constants import (
    AUTO_PROMOTION,
    EARLY_REVIEW_N,
    FEATURE_DEPLOY_EPOCH,
    FEATURE_DEPLOY_EPOCH_SOURCE,
    FEATURE_KEY,
    LAB_COMPARE_VARIANTS,
    LAB_ID,
    PRIMARY_REVIEW_N,
    PROMOTION_REVIEW_N,
    RESEARCH_ONLY_LABEL,
    RULE_VERSION,
    SHADOW_VARIANTS,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_CONTINUATION,
    STATUS_DEFERRED,
    STATUS_INSUFFICIENT_MARKET_DATA,
    STATUS_PRE_EXISTING_EXCLUDED,
    STATUS_UNRESOLVED,
    VARIANT_R0,
    ALL_VARIANTS,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.engine import (
    PathSnapshot,
    evaluate_variant_exit,
    ma_relation_label,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.entities import (
    UpbitExitOptimizationShadowV3EnrollmentEntity,
    UpbitExitOptimizationShadowV3VariantEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.policy import (
    DEFAULT_POLICY,
    load_policy_bundle,
    variant_policy_id,
)
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
    compute_round_trip_pnl,
)

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
        getattr(settings, "upbit_exit_optimization_shadow_v3_enabled", True)
    )


def deployment_epoch(
    settings: Any | None = None,
    session: Session | None = None,
) -> datetime:
    settings = settings or get_settings()
    raw = str(
        getattr(settings, "upbit_exit_optimization_shadow_v3_deployed_at", "") or ""
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

            epoch, _ = get_or_create_feature_epoch(
                session,
                feature_key=FEATURE_KEY,
                seed_epoch=FEATURE_DEPLOY_EPOCH,
                seed_source=FEATURE_DEPLOY_EPOCH_SOURCE,
            )
            return _as_utc(epoch) or FEATURE_DEPLOY_EPOCH
        except Exception:  # noqa: BLE001
            pass
    return FEATURE_DEPLOY_EPOCH


def _gain_pct(entry: Decimal, price: Decimal) -> float:
    if entry <= ZERO:
        return 0.0
    return float((price - entry) / entry * HUNDRED)


def _init_variant_row(
    *,
    enrollment_id: int,
    binding_id: int,
    variant_id: str,
    policy_version: str,
    entry_fee: Decimal | None,
    policy: Any,
) -> UpbitExitOptimizationShadowV3VariantEntity:
    rt_fee = Decimal(str(policy.round_trip_fee_pct))
    return UpbitExitOptimizationShadowV3VariantEntity(
        enrollment_id=enrollment_id,
        binding_id=binding_id,
        variant_id=variant_id,
        policy_version=policy_version,
        status=STATUS_ACTIVE,
        estimated_entry_fee=entry_fee,
        estimated_round_trip_fee=rt_fee,
        meta_json={"research_label": RESEARCH_ONLY_LABEL},
    )


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
    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}

    existing = session.scalar(
        select(UpbitExitOptimizationShadowV3EnrollmentEntity).where(
            UpbitExitOptimizationShadowV3EnrollmentEntity.binding_id
            == int(binding_id)
        )
    )
    if existing is not None:
        return {
            "ok": True,
            "duplicate": True,
            "enrollment_id": int(existing.enrollment_id),
        }

    deploy = deployment_epoch(settings, session=session)
    opened = _as_utc(entry_at) or _utc_now()
    status = STATUS_ACTIVE
    if opened < deploy:
        status = STATUS_PRE_EXISTING_EXCLUDED

    policy = load_policy_bundle(session)
    row = UpbitExitOptimizationShadowV3EnrollmentEntity(
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
        policy_version=policy.policy_version,
        status=status,
        research_only=True,
        path_state_json={
            "peak_price": str(entry_price),
            "mfe_pct": 0.0,
            "mae_pct": 0.0,
            "lab_id": LAB_ID,
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
    except Exception:  # noqa: BLE001
        pass

    session.add(row)
    session.flush()

    for vid in ALL_VARIANTS:
        session.add(
            _init_variant_row(
                enrollment_id=int(row.enrollment_id),
                binding_id=int(binding_id),
                variant_id=vid,
                policy_version=variant_policy_id(vid)
                if vid != VARIANT_R0
                else "CURRENT_REAL",
                entry_fee=entry_fee,
                policy=policy,
            )
        )
    session.flush()
    return {
        "ok": True,
        "duplicate": False,
        "enrollment_id": int(row.enrollment_id),
        "status": status,
    }


def _update_path_state(
    enrollment: UpbitExitOptimizationShadowV3EnrollmentEntity,
    *,
    price: Decimal,
    short_ma: Decimal | None,
    long_ma: Decimal | None,
    ma_dead_cross: bool,
) -> PathSnapshot:
    entry = Decimal(str(enrollment.entry_price))
    path = dict(enrollment.path_state_json or {})
    peak = Decimal(str(path.get("peak_price") or entry))
    if price > peak:
        peak = price
        path["peak_price"] = str(peak)
    gain = _gain_pct(entry, price)
    mfe = max(float(path.get("mfe_pct") or 0), gain)
    mae = min(float(path.get("mae_pct") or 0), gain)
    path["mfe_pct"] = mfe
    path["mae_pct"] = mae
    path["last_price"] = str(price)
    enrollment.path_state_json = path

    entry_at = _as_utc(enrollment.entry_at) or _utc_now()
    hold_s = max(0.0, ((_utc_now() - entry_at).total_seconds()))

    return PathSnapshot(
        entry_price=entry,
        current_price=price,
        peak_price=peak,
        hold_seconds=hold_s,
        mfe_pct=mfe,
        mae_pct=mae,
        short_ma=short_ma,
        long_ma=long_ma,
        ma_dead_cross=ma_dead_cross,
    )


def _complete_variant(
    variant: UpbitExitOptimizationShadowV3VariantEntity,
    enrollment: UpbitExitOptimizationShadowV3EnrollmentEntity,
    *,
    exit_reason: str,
    exit_price: Decimal,
    exit_at: datetime,
    trigger_reason: str | None,
    defer_reason: str | None = None,
) -> None:
    entry = Decimal(str(enrollment.entry_price))
    qty = Decimal(str(enrollment.entry_quantity or ZERO))
    if qty <= ZERO:
        qty = Decimal("1")
    pnl = compute_round_trip_pnl(
        entry_price=entry,
        exit_price=exit_price,
        quantity=qty,
        buy_fee=enrollment.entry_fee,
    )
    entry_at = _as_utc(enrollment.entry_at) or exit_at
    hold_s = max(0.0, (exit_at - entry_at).total_seconds())
    path = dict(enrollment.path_state_json or {})

    variant.status = STATUS_COMPLETED
    variant.shadow_exit_reason = exit_reason[:64]
    variant.shadow_exit_at = exit_at
    variant.shadow_exit_price = exit_price
    variant.shadow_gross_pnl = Decimal(str(round(pnl["gross_pnl"], 4)))
    variant.shadow_estimated_exit_fee = Decimal(
        str(round(pnl["fee"] - float(enrollment.entry_fee or 0), 4))
    )
    variant.shadow_estimated_net_pnl = Decimal(str(round(pnl["net_pnl"], 4)))
    variant.holding_seconds = Decimal(str(round(hold_s, 3)))
    variant.mfe_pct = Decimal(str(round(float(path.get("mfe_pct") or 0), 6)))
    variant.mae_pct = Decimal(str(round(float(path.get("mae_pct") or 0), 6)))
    variant.peak_profit_pct = Decimal(
        str(round(_gain_pct(entry, Decimal(str(path.get("peak_price") or entry))), 6))
    )
    variant.current_profit_pct = Decimal(str(round(_gain_pct(entry, exit_price), 6)))
    variant.trigger_reason = trigger_reason
    variant.defer_reason = defer_reason
    variant.shadow_terminal_at = exit_at
    variant.continuation_active = False


def observe_price_tick(
    session: Session,
    *,
    binding_id: int,
    price: Decimal,
    observed_at: datetime | None = None,
    short_ma: Decimal | None = None,
    long_ma: Decimal | None = None,
    ma_dead_cross: bool = False,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}

    enrollment = session.scalar(
        select(UpbitExitOptimizationShadowV3EnrollmentEntity).where(
            UpbitExitOptimizationShadowV3EnrollmentEntity.binding_id
            == int(binding_id)
        )
    )
    if enrollment is None:
        return {"ok": False, "reason": "NOT_FOUND"}
    if enrollment.status not in (STATUS_ACTIVE, STATUS_CONTINUATION):
        return {"ok": False, "reason": "NOT_OBSERVING"}

    now = _as_utc(observed_at) or _utc_now()
    snap = _update_path_state(
        enrollment,
        price=price,
        short_ma=short_ma,
        long_ma=long_ma,
        ma_dead_cross=ma_dead_cross,
    )
    policy = load_policy_bundle(session, policy_version=enrollment.policy_version)
    variants = list(
        session.scalars(
            select(UpbitExitOptimizationShadowV3VariantEntity).where(
                UpbitExitOptimizationShadowV3VariantEntity.enrollment_id
                == int(enrollment.enrollment_id),
                UpbitExitOptimizationShadowV3VariantEntity.variant_id.in_(
                    SHADOW_VARIANTS
                ),
            )
        )
    )

    exits = 0
    for var in variants:
        if var.status not in (STATUS_ACTIVE, STATUS_DEFERRED, STATUS_CONTINUATION):
            continue
        var.short_ma = short_ma
        var.long_ma = long_ma
        var.ma_relation = ma_relation_label(short_ma, long_ma)
        var.current_profit_pct = Decimal(str(round(
            _gain_pct(snap.entry_price, price), 6
        )))
        var.peak_profit_pct = Decimal(str(round(
            _gain_pct(snap.entry_price, snap.peak_price), 6
        )))

        decision = evaluate_variant_exit(snap, policy, var.variant_id)
        if decision.defer:
            var.status = STATUS_DEFERRED
            var.defer_reason = decision.defer_reason
            var.deferred_trailing_count = int(var.deferred_trailing_count or 0) + 1
            var.trigger_reason = decision.trigger_reason
            continue

        if decision.should_exit:
            _complete_variant(
                var,
                enrollment,
                exit_reason=str(decision.exit_reason or "UNKNOWN"),
                exit_price=price,
                exit_at=now,
                trigger_reason=decision.trigger_reason,
            )
            exits += 1

    session.flush()
    return {"ok": True, "binding_id": int(binding_id), "shadow_exits": exits}


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

    enrollment = session.scalar(
        select(UpbitExitOptimizationShadowV3EnrollmentEntity).where(
            UpbitExitOptimizationShadowV3EnrollmentEntity.binding_id
            == int(binding_id)
        )
    )
    if enrollment is None:
        return {"ok": False, "reason": "NOT_FOUND"}

    terminal_at = _as_utc(exit_at) or _utc_now()
    enrollment.real_exit_reason = str(exit_reason or "UNKNOWN")[:64]
    enrollment.real_exit_at = terminal_at
    enrollment.real_closed_at = terminal_at
    if exit_price is not None:
        enrollment.real_exit_price = exit_price
    if gross_pnl is not None:
        enrollment.real_gross_pnl = Decimal(str(round(gross_pnl, 4)))
    if fee is not None:
        enrollment.real_fees = Decimal(str(round(fee, 4)))
    if net_pnl is not None:
        enrollment.real_net_pnl = Decimal(str(round(net_pnl, 4)))
    entry_at = _as_utc(enrollment.entry_at)
    if entry_at:
        enrollment.real_holding_seconds = Decimal(
            str(round(max(0.0, (terminal_at - entry_at).total_seconds()), 3))
        )

    # R0 = REAL baseline
    r0 = session.scalar(
        select(UpbitExitOptimizationShadowV3VariantEntity).where(
            UpbitExitOptimizationShadowV3VariantEntity.binding_id == int(binding_id),
            UpbitExitOptimizationShadowV3VariantEntity.variant_id == VARIANT_R0,
        )
    )
    if r0 is not None:
        r0.status = STATUS_COMPLETED
        r0.baseline_terminal_at = terminal_at
        r0.shadow_terminal_at = terminal_at
        r0.shadow_exit_reason = enrollment.real_exit_reason
        r0.shadow_exit_at = terminal_at
        if exit_price is not None:
            r0.shadow_exit_price = exit_price
        r0.shadow_gross_pnl = enrollment.real_gross_pnl
        r0.shadow_estimated_net_pnl = enrollment.real_net_pnl
        r0.holding_seconds = enrollment.real_holding_seconds
        path = dict(enrollment.path_state_json or {})
        r0.mfe_pct = Decimal(str(round(float(path.get("mfe_pct") or 0), 6)))
        r0.mae_pct = Decimal(str(round(float(path.get("mae_pct") or 0), 6)))

    # shadow variants: REAL terminal boundary unless already completed/deferred-continuing
    shadow_vars = list(
        session.scalars(
            select(UpbitExitOptimizationShadowV3VariantEntity).where(
                UpbitExitOptimizationShadowV3VariantEntity.binding_id
                == int(binding_id),
                UpbitExitOptimizationShadowV3VariantEntity.variant_id.in_(
                    SHADOW_VARIANTS
                ),
            )
        )
    )
    continuation = False
    if exit_price is not None:
        entry = Decimal(str(enrollment.entry_price))
        qty = Decimal(str(enrollment.entry_quantity or ZERO)) or Decimal("1")
        for var in shadow_vars:
            if var.status == STATUS_COMPLETED:
                continue
            if var.status in (STATUS_DEFERRED, STATUS_ACTIVE):
                var.continuation_active = True
                var.status = STATUS_CONTINUATION
                var.baseline_terminal_at = terminal_at
                continuation = True
                continue
            # 미완료 variant → REAL boundary (가짜 미래가격 금지)
            _complete_variant(
                var,
                enrollment,
                exit_reason=f"REAL_BOUNDARY_{enrollment.real_exit_reason}",
                exit_price=exit_price,
                exit_at=terminal_at,
                trigger_reason="REAL_TERMINAL_BOUNDARY",
            )

    if continuation:
        enrollment.status = STATUS_CONTINUATION
    else:
        enrollment.status = STATUS_COMPLETED
        enrollment.completed_at = _utc_now()

    session.flush()
    return {
        "ok": True,
        "enrollment_id": int(enrollment.enrollment_id),
        "continuation": continuation,
    }


def pair_variant_row(
    enrollment: UpbitExitOptimizationShadowV3EnrollmentEntity,
    variant: UpbitExitOptimizationShadowV3VariantEntity,
) -> dict[str, Any]:
    baseline_net = enrollment.real_net_pnl
    shadow_net = variant.shadow_estimated_net_pnl
    paired = (
        baseline_net is not None
        and shadow_net is not None
        and enrollment.real_exit_at is not None
        and variant.shadow_exit_at is not None
        and variant.status == STATUS_COMPLETED
    )
    delta = None
    if paired:
        delta = float(shadow_net) - float(baseline_net)
    return {
        "paired_valid": paired,
        "binding_id": int(enrollment.binding_id),
        "variant_id": variant.variant_id,
        "baseline_net": float(baseline_net) if baseline_net is not None else None,
        "shadow_net": float(shadow_net) if shadow_net is not None else None,
        "delta_net": delta,
        "baseline_hold_seconds": float(enrollment.real_holding_seconds)
        if enrollment.real_holding_seconds is not None
        else None,
        "shadow_hold_seconds": float(variant.holding_seconds)
        if variant.holding_seconds is not None
        else None,
        "baseline_fees": float(enrollment.real_fees)
        if enrollment.real_fees is not None
        else None,
        "shadow_fees": float(
            (variant.estimated_entry_fee or ZERO)
            + (variant.shadow_estimated_exit_fee or ZERO)
        )
        if variant.shadow_estimated_exit_fee is not None
        else None,
        "entry_at": enrollment.entry_at.isoformat() if enrollment.entry_at else None,
        "defer_reason": variant.defer_reason,
        "deferred_trailing_count": int(variant.deferred_trailing_count or 0),
    }


def _readiness_label(n: int) -> str:
    if n < EARLY_REVIEW_N:
        return "SAMPLE_PENDING"
    if n < PRIMARY_REVIEW_N:
        return "EARLY_REVIEW"
    if n < PROMOTION_REVIEW_N:
        return "PRIMARY_REVIEW"
    return "PROMOTION_REVIEW_ELIGIBLE"


def summarize_exit_optimization_v3_lab(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
    include_rows: bool = False,
    row_limit: int = 200,
) -> dict[str, Any]:
    eq = select(UpbitExitOptimizationShadowV3EnrollmentEntity)
    if user_broker_account_id is not None:
        eq = eq.where(
            UpbitExitOptimizationShadowV3EnrollmentEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    enrollments = list(session.scalars(eq))
    epoch = deployment_epoch(session=session)

    per_variant: dict[str, Any] = {}
    all_pairs: list[dict[str, Any]] = []

    for vid in LAB_COMPARE_VARIANTS:
        nets_b: list[float] = []
        nets_s: list[float] = []
        deltas: list[float] = []
        holds_b: list[float] = []
        holds_s: list[float] = []
        fees_b: list[float] = []
        fees_s: list[float] = []
        lt30_b = lt30_s = 0
        lt30_net_b = lt30_net_s = 0.0
        trailing_b = trailing_s = 0
        deferred = 0
        unresolved = 0
        valid_n = 0

        for enr in enrollments:
            if not bool(getattr(enr, "included_in_research_metrics", True)):
                continue
            if vid == VARIANT_R0:
                if enr.real_net_pnl is not None and enr.real_exit_at:
                    valid_n += 1
                    nets_b.append(float(enr.real_net_pnl))
                    nets_s.append(float(enr.real_net_pnl))
                    if enr.real_holding_seconds is not None:
                        holds_b.append(float(enr.real_holding_seconds))
                        holds_s.append(float(enr.real_holding_seconds))
                    if enr.real_fees is not None:
                        fees_b.append(float(enr.real_fees))
                        fees_s.append(float(enr.real_fees))
                    hs = float(enr.real_holding_seconds or 0)
                    if hs < 30:
                        lt30_b += 1
                        lt30_net_b += float(enr.real_net_pnl)
                    if "TRAIL" in str(enr.real_exit_reason or "").upper():
                        trailing_b += 1
                continue

            var = session.scalar(
                select(UpbitExitOptimizationShadowV3VariantEntity).where(
                    UpbitExitOptimizationShadowV3VariantEntity.binding_id
                    == int(enr.binding_id),
                    UpbitExitOptimizationShadowV3VariantEntity.variant_id == vid,
                )
            )
            if var is None:
                continue
            if var.status in (STATUS_UNRESOLVED, STATUS_INSUFFICIENT_MARKET_DATA):
                unresolved += 1
                continue
            pair = pair_variant_row(enr, var)
            if pair["paired_valid"]:
                valid_n += 1
                all_pairs.append(pair)
                b = float(pair["baseline_net"])
                s = float(pair["shadow_net"])
                nets_b.append(b)
                nets_s.append(s)
                deltas.append(float(pair["delta_net"]))
                if pair["baseline_hold_seconds"] is not None:
                    holds_b.append(float(pair["baseline_hold_seconds"]))
                if pair["shadow_hold_seconds"] is not None:
                    holds_s.append(float(pair["shadow_hold_seconds"]))
                if pair["baseline_fees"] is not None:
                    fees_b.append(float(pair["baseline_fees"]))
                if pair["shadow_fees"] is not None:
                    fees_s.append(float(pair["shadow_fees"]))
                hs_b = float(pair["baseline_hold_seconds"] or 0)
                hs_s = float(pair["shadow_hold_seconds"] or 0)
                if hs_b < 30:
                    lt30_b += 1
                    lt30_net_b += b
                if hs_s < 30:
                    lt30_s += 1
                    lt30_net_s += s
                if "TRAIL" in str(enr.real_exit_reason or "").upper():
                    trailing_b += 1
                if "TRAIL" in str(var.shadow_exit_reason or "").upper():
                    trailing_s += 1
            deferred += int(var.deferred_trailing_count or 0)

        def _pf(nets: list[float]) -> float | None:
            wins = sum(n for n in nets if n > 0)
            losses = abs(sum(n for n in nets if n <= 0))
            if not nets:
                return None
            return round(wins / losses, 6) if losses > 0 else None

        def _mdd(nets: list[float]) -> float:
            cum = 0.0
            peak = 0.0
            mdd = 0.0
            for n in nets:
                cum += n
                peak = max(peak, cum)
                mdd = min(mdd, cum - peak)
            return round(mdd, 4)

        base_net = round(sum(nets_b), 4) if nets_b else 0.0
        sh_net = round(sum(nets_s), 4) if nets_s else 0.0
        per_variant[vid] = {
            "TOTAL_ENROLLED": len(enrollments),
            "VALID_PAIRED_N": valid_n,
            "UNRESOLVED_COUNT": unresolved,
            "BASELINE_NET": base_net,
            "SHADOW_NET": sh_net,
            "DELTA_NET": round(sh_net - base_net, 4) if nets_b else None,
            "AVG_DELTA_PER_TRADE": round(sum(deltas) / len(deltas), 4)
            if deltas
            else None,
            "BASELINE_PF": _pf(nets_b),
            "SHADOW_PF": _pf(nets_s),
            "BASELINE_WIN_RATE": round(
                sum(1 for n in nets_b if n > 0) / len(nets_b), 4
            )
            if nets_b
            else None,
            "SHADOW_WIN_RATE": round(
                sum(1 for n in nets_s if n > 0) / len(nets_s), 4
            )
            if nets_s
            else None,
            "BASELINE_MDD": _mdd(nets_b) if nets_b else None,
            "SHADOW_MDD": _mdd(nets_s) if nets_s else None,
            "BASELINE_AVG_HOLD": round(sum(holds_b) / len(holds_b), 1)
            if holds_b
            else None,
            "SHADOW_AVG_HOLD": round(sum(holds_s) / len(holds_s), 1)
            if holds_s
            else None,
            "BASELINE_FEES": round(sum(fees_b), 4) if fees_b else None,
            "SHADOW_ESTIMATED_FEES": round(sum(fees_s), 4) if fees_s else None,
            "FEE_SAVING_ESTIMATE": round(sum(fees_b) - sum(fees_s), 4)
            if fees_b and fees_s
            else None,
            "TRAILING_EXIT_COUNT": trailing_s if vid != VARIANT_R0 else trailing_b,
            "DEFERRED_TRAILING_COUNT": deferred,
            "LT30S_BASELINE_COUNT": lt30_b,
            "LT30S_SHADOW_COUNT": lt30_s,
            "LT30S_BASELINE_NET": round(lt30_net_b, 4),
            "LT30S_SHADOW_NET": round(lt30_net_s, 4),
            "READINESS": _readiness_label(valid_n),
            "AUTO_PROMOTION": AUTO_PROMOTION,
        }

    max_n = max((per_variant[v]["VALID_PAIRED_N"] for v in SHADOW_VARIANTS), default=0)
    return {
        "ok": True,
        "LAB_ID": LAB_ID,
        "RULE_VERSION": RULE_VERSION,
        "REAL_POLICY_CHANGED": False,
        "SHADOW_ONLY": True,
        "FORWARD_START_AT": epoch.isoformat(),
        "READINESS": _readiness_label(max_n),
        "VALID_PAIRED_N_MAX": max_n,
        "VARIANTS": per_variant,
        "VARIANT_LABELS": {
            VARIANT_R0: "R0 CURRENT_REAL baseline",
            "E1": "E1 FEE_AWARE_TRAILING",
            "E2": "E2 PEAK_PROFIT_TIERED_TRAILING",
            "E3": "E3 MA_CONFIRM_TRAILING",
            "E4": "E4 ANTI_CHURN_TRAILING",
        },
        "GATES": {
            "EARLY_REVIEW_N": EARLY_REVIEW_N,
            "PRIMARY_REVIEW_N": PRIMARY_REVIEW_N,
            "PROMOTION_REVIEW_N": PROMOTION_REVIEW_N,
        },
        "DEFAULT_POLICY": DEFAULT_POLICY.to_dict(),
        "rows": all_pairs[:row_limit] if include_rows else None,
    }


def list_observations(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
    variant: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    q = (
        select(UpbitExitOptimizationShadowV3VariantEntity)
        .join(
            UpbitExitOptimizationShadowV3EnrollmentEntity,
            UpbitExitOptimizationShadowV3VariantEntity.enrollment_id
            == UpbitExitOptimizationShadowV3EnrollmentEntity.enrollment_id,
        )
        .order_by(UpbitExitOptimizationShadowV3VariantEntity.variant_row_id.desc())
    )
    if user_broker_account_id is not None:
        q = q.where(
            UpbitExitOptimizationShadowV3EnrollmentEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    if variant:
        q = q.where(
            UpbitExitOptimizationShadowV3VariantEntity.variant_id == str(variant).upper()
        )
    total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = list(session.scalars(q.offset(offset).limit(limit)))

    items = []
    for var in rows:
        enr = session.get(
            UpbitExitOptimizationShadowV3EnrollmentEntity, int(var.enrollment_id)
        )
        items.append(
            {
                "variant_row_id": int(var.variant_row_id),
                "binding_id": int(var.binding_id),
                "variant_id": var.variant_id,
                "symbol": enr.symbol if enr else None,
                "status": var.status,
                "real_exit_reason": enr.real_exit_reason if enr else None,
                "shadow_exit_reason": var.shadow_exit_reason,
                "real_net_pnl": str(enr.real_net_pnl) if enr and enr.real_net_pnl else None,
                "shadow_estimated_net_pnl": str(var.shadow_estimated_net_pnl)
                if var.shadow_estimated_net_pnl
                else None,
                "mfe_pct": str(var.mfe_pct) if var.mfe_pct is not None else None,
                "mae_pct": str(var.mae_pct) if var.mae_pct is not None else None,
                "defer_reason": var.defer_reason,
                "deferred_trailing_count": int(var.deferred_trailing_count or 0),
                "continuation_active": bool(var.continuation_active),
            }
        )
    return {"ok": True, "total": int(total), "items": items, "limit": limit, "offset": offset}
