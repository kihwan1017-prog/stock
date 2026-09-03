"""Profitability Improvement Shadow Lab V1 — service (REAL mutation 0)."""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.candidate_ranking import (
    rank_universe,
)
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.constants import (
    AUTO_PROMOTION,
    CANDIDATE_EARLY_REVIEW_N,
    CANDIDATE_PRIMARY_REVIEW_N,
    CANDIDATE_PROMOTION_REVIEW_N,
    EXIT_EARLY_REVIEW_N,
    EXIT_PRIMARY_REVIEW_N,
    EXIT_PROMOTION_REVIEW_N,
    FEATURE_DEPLOY_EPOCH,
    FEATURE_DEPLOY_EPOCH_SOURCE,
    FEATURE_KEY,
    LAB_A,
    LAB_A_LABELS,
    LAB_A_VARIANTS,
    LAB_B,
    LAB_B_LABELS,
    LAB_B_VARIANTS,
    LAB_C,
    LAB_C_LABELS,
    LAB_C_VARIANTS,
    LAB_ID,
    REENTRY_EARLY_REVIEW_N,
    REENTRY_PRIMARY_REVIEW_N,
    REENTRY_PROMOTION_REVIEW_N,
    RESEARCH_ONLY_LABEL,
    RULE_VERSION,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_PENDING_OUTCOME,
    STATUS_PRE_EXISTING_EXCLUDED,
    VARIANT_A0,
    VARIANT_B0,
    VARIANT_C0,
    VARIANT_C2,
    VARIANT_C3,
)
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.entities import (
    UpbitProfitabilityCandidateRefreshEntity,
    UpbitProfitabilityExitEnrollmentEntity,
    UpbitProfitabilityExitVariantEntity,
    UpbitProfitabilityReentryEventEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.exit_engine import (
    PathSnapshot,
    evaluate_variant_exit,
)
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.reentry_engine import (
    decide_reentry_block,
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
        getattr(settings, "upbit_profitability_improvement_shadow_enabled", True)
    )


def deployment_epoch(
    settings: Any | None = None, session: Session | None = None
) -> datetime:
    settings = settings or get_settings()
    raw = str(
        getattr(settings, "upbit_profitability_improvement_shadow_deployed_at", "")
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


def _readiness(n: int, early: int, primary: int, promo: int) -> str:
    if n >= promo:
        return "PROMOTION_REVIEW_ELIGIBLE"
    if n >= primary:
        return "PRIMARY_REVIEW"
    if n >= early:
        return "EARLY_REVIEW"
    return "SAMPLE_PENDING"


def _corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 4)


def _mean(xs: list[float]) -> float | None:
    return round(statistics.mean(xs), 4) if xs else None


# ---------- Lab A ----------


def observe_candidate_refresh(
    session: Session,
    *,
    user_broker_account_id: int,
    scanner_run_id: str,
    selection_id: int | None,
    strategy_id: int | None,
    observed_at: datetime,
    universe_rows: list[dict[str, Any]],
    settings: Any | None = None,
) -> dict[str, Any]:
    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}
    run_id = str(scanner_run_id or "").strip()
    if not run_id:
        return {"ok": False, "reason": "MISSING_SCANNER_RUN"}

    existing = session.scalar(
        select(UpbitProfitabilityCandidateRefreshEntity).where(
            UpbitProfitabilityCandidateRefreshEntity.user_broker_account_id
            == int(user_broker_account_id),
            UpbitProfitabilityCandidateRefreshEntity.scanner_run_id == run_id,
        )
    )
    if existing is not None:
        return {"ok": True, "duplicate": True, "refresh_id": int(existing.refresh_id)}

    obs = _as_utc(observed_at) or _utc_now()
    deploy = deployment_epoch(settings, session=session)
    if obs < deploy:
        return {"ok": False, "reason": "PRE_EPOCH", "SHADOW_ONLY": True}

    rankings = {
        vid: rank_universe(universe_rows, variant=vid, top_n=10)
        for vid in LAB_A_VARIANTS
    }
    row = UpbitProfitabilityCandidateRefreshEntity(
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=strategy_id,
        scanner_run_id=run_id,
        selection_id=selection_id,
        observed_at=obs,
        rule_version=RULE_VERSION,
        research_only=True,
        status=STATUS_PENDING_OUTCOME,
        universe_json=[
            {
                "symbol": str(r.get("symbol") or "").upper(),
                "rank": r.get("rank") or r.get("scanner_rank"),
                "score": r.get("score") or r.get("scanner_score"),
                "liquidity": r.get("liquidity") or r.get("trade_value_24h"),
                # feature 스냅샷 — A1~A3 분화용 (미래 수익률 금지)
                "technical_metrics": dict(r.get("technical_metrics") or {}),
            }
            for r in universe_rows
            if str(r.get("symbol") or "").startswith("KRW-")
        ],
        rankings_json=rankings,
        outcomes_json={},
        meta_json={"lab_id": LAB_ID, "lab": LAB_A, "label": RESEARCH_ONLY_LABEL},
    )
    session.add(row)
    session.flush()
    return {
        "ok": True,
        "refresh_id": int(row.refresh_id),
        "SHADOW_ONLY": True,
        "REAL_POLICY_CHANGED": False,
    }


def fill_candidate_outcomes(
    session: Session,
    *,
    limit: int = 50,
    settings: Any | None = None,
) -> dict[str, Any]:
    """Scheduler: candle 기반 forward outcome (ranking 재계산 금지)."""

    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}

    from sqlalchemy import text

    pending = list(
        session.scalars(
            select(UpbitProfitabilityCandidateRefreshEntity)
            .where(
                UpbitProfitabilityCandidateRefreshEntity.status
                == STATUS_PENDING_OUTCOME
            )
            .order_by(UpbitProfitabilityCandidateRefreshEntity.observed_at.asc())
            .limit(limit)
        )
    )
    filled = 0
    for row in pending:
        obs = _as_utc(row.observed_at)
        if obs is None:
            continue
        # 60m horizon 확보 여부
        if _utc_now() < obs + timedelta(minutes=61):
            continue
        symbols: set[str] = set()
        for vid, ranks in dict(row.rankings_json or {}).items():
            for item in ranks or []:
                symbols.add(str(item.get("symbol") or "").upper())
        if not symbols:
            row.status = STATUS_COMPLETED
            row.outcomes_json = {}
            filled += 1
            continue

        outcomes: dict[str, Any] = {}
        for sym in symbols:
            px_rows = session.execute(
                text(
                    """
                    SELECT c.candle_at, c.close_price, c.high_price, c.low_price
                    FROM market.candle_minute c
                    JOIN market.instrument i ON i.instrument_id = c.instrument_id
                    WHERE i.exchange_code='UPBIT' AND i.symbol=:sym AND c.timeframe=1
                      AND c.candle_at >= :s AND c.candle_at <= :e
                    ORDER BY c.candle_at
                    """
                ),
                {
                    "sym": sym,
                    "s": obs - timedelta(minutes=1),
                    "e": obs + timedelta(minutes=65),
                },
            ).mappings().all()
            if not px_rows:
                continue
            series = [
                (
                    r["candle_at"].astimezone(timezone.utc),
                    float(r["close_price"]),
                    float(r["high_price"] or r["close_price"]),
                    float(r["low_price"] or r["close_price"]),
                )
                for r in px_rows
            ]

            def price_at(t: datetime) -> float | None:
                target = t.replace(second=0, microsecond=0)
                best = None
                for ct, close, _, _ in series:
                    if ct <= target:
                        best = close
                    else:
                        break
                return best

            entry = price_at(obs)
            if entry is None or entry <= 0:
                continue
            hor: dict[str, Any] = {}
            for m in (1, 3, 5, 10, 30, 60):
                t1 = obs + timedelta(minutes=m)
                highs, lows, last = [], [], None
                for ct, close, high, low in series:
                    if ct < obs.replace(second=0, microsecond=0):
                        continue
                    if ct > t1.replace(second=0, microsecond=0):
                        break
                    highs.append(high)
                    lows.append(low)
                    last = close
                if last is None:
                    last = price_at(t1)
                if last is None:
                    hor[f"{m}M"] = {"RETURN": None, "MFE": None, "MAE": None}
                    continue
                peak = max(highs) if highs else last
                trough = min(lows) if lows else last
                hor[f"{m}M"] = {
                    "RETURN": round((last - entry) / entry * 100.0, 4),
                    "MFE": round((peak - entry) / entry * 100.0, 4),
                    "MAE": round((trough - entry) / entry * 100.0, 4),
                }
            outcomes[sym] = hor
        row.outcomes_json = outcomes
        row.status = STATUS_COMPLETED
        filled += 1
    session.flush()
    return {"ok": True, "filled": filled, "SHADOW_ONLY": True}


# ---------- Lab B ----------


def enroll_exit_on_open(
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
        select(UpbitProfitabilityExitEnrollmentEntity).where(
            UpbitProfitabilityExitEnrollmentEntity.binding_id == int(binding_id)
        )
    )
    if existing is not None:
        return {
            "ok": True,
            "duplicate": True,
            "enrollment_id": int(existing.enrollment_id),
        }

    opened = _as_utc(entry_at) or _utc_now()
    deploy = deployment_epoch(settings, session=session)
    status = STATUS_ACTIVE if opened >= deploy else STATUS_PRE_EXISTING_EXCLUDED
    enr = UpbitProfitabilityExitEnrollmentEntity(
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
        path_state_json={
            "peak_price": str(entry_price),
            "mfe_pct": 0.0,
            "mae_pct": 0.0,
            "lab": LAB_B,
        },
    )
    session.add(enr)
    session.flush()
    for vid in LAB_B_VARIANTS:
        session.add(
            UpbitProfitabilityExitVariantEntity(
                enrollment_id=int(enr.enrollment_id),
                binding_id=int(binding_id),
                variant_id=vid,
                status=status,
                meta_json={"lab": LAB_B, "label": LAB_B_LABELS[vid]},
            )
        )
    session.flush()
    return {
        "ok": True,
        "enrollment_id": int(enr.enrollment_id),
        "SHADOW_ONLY": True,
        "REAL_POLICY_CHANGED": False,
    }


def observe_exit_price(
    session: Session,
    *,
    binding_id: int,
    price: Decimal,
    observed_at: datetime | None = None,
    short_ma: Decimal | None = None,
    long_ma: Decimal | None = None,
    macd: float | None = None,
    ma_dead_cross: bool = False,
    settings: Any | None = None,
) -> dict[str, Any]:
    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}
    enr = session.scalar(
        select(UpbitProfitabilityExitEnrollmentEntity).where(
            UpbitProfitabilityExitEnrollmentEntity.binding_id == int(binding_id)
        )
    )
    if enr is None or enr.status != STATUS_ACTIVE:
        return {"ok": False, "reason": "NOT_ACTIVE"}

    now = _as_utc(observed_at) or _utc_now()
    path = dict(enr.path_state_json or {})
    peak = Decimal(str(path.get("peak_price") or enr.entry_price))
    if price > peak:
        peak = price
    entry = Decimal(str(enr.entry_price))
    mfe = float((peak - entry) / entry * HUNDRED) if entry > 0 else 0.0
    mae = float((price - entry) / entry * HUNDRED) if entry > 0 else 0.0
    if mae > 0:
        mae = float(path.get("mae_pct") or 0.0)
    else:
        mae = min(float(path.get("mae_pct") or 0.0), mae)
    hold = (now - _as_utc(enr.entry_at)).total_seconds() if enr.entry_at else 0.0
    path.update(
        {
            "peak_price": str(peak),
            "mfe_pct": mfe,
            "mae_pct": mae,
            "last_price": str(price),
            "last_at": now.isoformat(),
        }
    )
    enr.path_state_json = path

    snap = PathSnapshot(
        entry_price=entry,
        current_price=price,
        peak_price=peak,
        hold_seconds=hold,
        mfe_pct=mfe,
        mae_pct=mae,
        short_ma=short_ma,
        long_ma=long_ma,
        macd=macd,
        ma_dead_cross=ma_dead_cross,
    )
    variants = list(
        session.scalars(
            select(UpbitProfitabilityExitVariantEntity).where(
                UpbitProfitabilityExitVariantEntity.enrollment_id
                == int(enr.enrollment_id),
                UpbitProfitabilityExitVariantEntity.status == STATUS_ACTIVE,
            )
        )
    )
    for v in variants:
        if v.variant_id == VARIANT_B0:
            continue  # baseline = REAL exit only
        decision = evaluate_variant_exit(snap, v.variant_id)
        if decision.defer:
            v.defer_count = int(v.defer_count or 0) + 1
            st = dict(v.state_json or {})
            st["last_defer"] = decision.defer_reason
            v.state_json = st
            continue
        if decision.should_exit:
            qty = Decimal(str(enr.entry_quantity or 0))
            pnl = compute_round_trip_pnl(
                entry_price=entry,
                exit_price=price,
                quantity=qty if qty > 0 else Decimal("1"),
                buy_fee=enr.entry_fee,
            )
            v.shadow_exit_reason = decision.exit_reason
            v.shadow_exit_at = now
            v.shadow_exit_price = price
            v.shadow_gross_pnl = Decimal(str(round(pnl["gross_pnl"], 4)))
            v.shadow_fees = Decimal(str(round(pnl["fee"], 4)))
            v.shadow_net_pnl = Decimal(str(round(pnl["net_pnl"], 4)))
            v.shadow_holding_seconds = Decimal(str(round(hold, 3)))
            v.shadow_mfe_pct = Decimal(str(round(mfe, 6)))
            v.status = STATUS_COMPLETED
    session.flush()
    return {"ok": True, "SHADOW_ONLY": True}


def finalize_exit_on_close(
    session: Session,
    *,
    binding_id: int,
    exit_at: datetime,
    exit_price: Decimal | None,
    exit_reason: str | None,
    gross_pnl: Decimal | None,
    fees: Decimal | None,
    net_pnl: Decimal | None,
    hold_seconds: float | None,
    settings: Any | None = None,
) -> dict[str, Any]:
    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}
    enr = session.scalar(
        select(UpbitProfitabilityExitEnrollmentEntity).where(
            UpbitProfitabilityExitEnrollmentEntity.binding_id == int(binding_id)
        )
    )
    if enr is None:
        return {"ok": False, "reason": "NOT_FOUND"}

    closed = _as_utc(exit_at) or _utc_now()
    enr.real_exit_at = closed
    enr.real_exit_price = exit_price
    enr.real_exit_reason = exit_reason
    enr.real_gross_pnl = gross_pnl
    enr.real_fees = fees
    enr.real_net_pnl = net_pnl
    if hold_seconds is not None:
        enr.real_holding_seconds = Decimal(str(hold_seconds))
    enr.completed_at = closed
    if enr.status == STATUS_ACTIVE:
        enr.status = STATUS_COMPLETED

    variants = list(
        session.scalars(
            select(UpbitProfitabilityExitVariantEntity).where(
                UpbitProfitabilityExitVariantEntity.enrollment_id
                == int(enr.enrollment_id)
            )
        )
    )
    for v in variants:
        if v.variant_id == VARIANT_B0:
            v.shadow_exit_reason = exit_reason
            v.shadow_exit_at = closed
            v.shadow_exit_price = exit_price
            v.shadow_gross_pnl = gross_pnl
            v.shadow_fees = fees
            v.shadow_net_pnl = net_pnl
            if hold_seconds is not None:
                v.shadow_holding_seconds = Decimal(str(hold_seconds))
            path = dict(enr.path_state_json or {})
            if path.get("mfe_pct") is not None:
                v.shadow_mfe_pct = Decimal(str(path["mfe_pct"]))
            v.net_delta = ZERO
            v.status = STATUS_COMPLETED
        elif v.status == STATUS_ACTIVE:
            # shadow가 REAL보다 늦게 청산 못 했으면 continuation: use REAL close as unresolved baseline compare
            # keep ACTIVE until scheduler forces; mark continuation with REAL price for paired delta if still open
            if exit_price is not None and enr.entry_quantity:
                # optional: do not force exit — leave ACTIVE for post-baseline continuation tracking
                st = dict(v.state_json or {})
                st["baseline_closed"] = True
                st["baseline_exit_at"] = closed.isoformat()
                v.state_json = st
        if v.shadow_net_pnl is not None and net_pnl is not None:
            v.net_delta = Decimal(str(v.shadow_net_pnl)) - Decimal(str(net_pnl))
    session.flush()
    # Lab D: REAL MA_DEAD_CROSS만 SHADOW enroll (실제 SELL 시점 변경 없음)
    # PostgreSQL: 예외 시 트랜잭션 오염 방지 — savepoint 사용
    try:
        reason_u = str(exit_reason or "").upper()
        if "MA_DEAD_CROSS" in reason_u and exit_price is not None:
            with session.begin_nested():
                enroll_ma_dc_event(
                    session,
                    user_broker_account_id=int(enr.user_broker_account_id),
                    binding_id=int(binding_id),
                    symbol=str(enr.symbol),
                    strategy_id=enr.strategy_id,
                    entry_order_id=enr.entry_order_id,
                    entry_at=enr.entry_at,
                    entry_price=enr.entry_price,
                    baseline_exit_at=closed,
                    baseline_exit_price=exit_price,
                    baseline_net_pnl=net_pnl,
                    baseline_fees=fees,
                )
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "SHADOW_ONLY": True, "REAL_POLICY_CHANGED": False}


def enroll_ma_dc_event(
    session: Session,
    *,
    user_broker_account_id: int,
    binding_id: int,
    symbol: str,
    strategy_id: int | None,
    entry_order_id: int | None,
    entry_at: datetime | None,
    entry_price: Decimal | None,
    baseline_exit_at: datetime,
    baseline_exit_price: Decimal,
    baseline_net_pnl: Decimal | None,
    baseline_fees: Decimal | None,
    settings: Any | None = None,
) -> dict[str, Any]:
    """MA Dead Cross Shadow Lab enroll — D0 baseline equality immediate."""

    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.entities import (
        UpbitProfitabilityMaDcEventEntity,
    )
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.ma_dc_engine import (
        MaDcSnapshot,
        decide_d0_baseline,
    )
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.constants import (
        LAB_D,
        LAB_D_VARIANTS,
        VARIANT_D0,
    )

    dup = session.scalar(
        select(UpbitProfitabilityMaDcEventEntity).where(
            UpbitProfitabilityMaDcEventEntity.user_broker_account_id
            == int(user_broker_account_id),
            UpbitProfitabilityMaDcEventEntity.binding_id == int(binding_id),
        )
    )
    if dup is not None:
        return {"ok": True, "duplicate": True, "event_id": int(dup.event_id)}

    be = _as_utc(baseline_exit_at) or _utc_now()
    snap = MaDcSnapshot(
        entry_price=float(entry_price or baseline_exit_price),
        baseline_exit_price=float(baseline_exit_price),
        current_price=float(baseline_exit_price),
        short_ma=None,
        long_ma=None,
    )
    outcomes = {VARIANT_D0: decide_d0_baseline(snap)}
    for vid in LAB_D_VARIANTS:
        if vid == VARIANT_D0:
            continue
        outcomes[vid] = {
            "WOULD_EXIT": False,
            "REASON": "PENDING_FORWARD",
            "STATUS": STATUS_ACTIVE,
        }
    row = UpbitProfitabilityMaDcEventEntity(
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=strategy_id,
        symbol=str(symbol).upper(),
        binding_id=int(binding_id),
        entry_order_id=entry_order_id,
        entry_at=_as_utc(entry_at),
        entry_price=entry_price,
        baseline_exit_at=be,
        baseline_exit_price=baseline_exit_price,
        baseline_net_pnl=baseline_net_pnl,
        baseline_fees=baseline_fees,
        rule_version=RULE_VERSION,
        status=STATUS_ACTIVE,
        research_only=True,
        variant_outcomes_json=outcomes,
        path_state_json={"confirm_ticks": 0, "peak_mfe_pct": 0.0},
        meta_json={"lab": LAB_D, "label": RESEARCH_ONLY_LABEL, "SHADOW_ONLY": True},
    )
    session.add(row)
    session.flush()
    return {
        "ok": True,
        "event_id": int(row.event_id),
        "SHADOW_ONLY": True,
        "REAL_POLICY_CHANGED": False,
    }


# ---------- Lab C ----------


def observe_reentry(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    prior_exit_at: datetime,
    reentry_at: datetime,
    entry_order_id: int | None,
    binding_id: int | None,
    strategy_id: int | None = None,
    prior_exit_binding_id: int | None = None,
    context: dict[str, Any] | None = None,
    settings: Any | None = None,
) -> dict[str, Any]:
    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}
    pe = _as_utc(prior_exit_at)
    re = _as_utc(reentry_at)
    if pe is None or re is None:
        return {"ok": False, "reason": "BAD_TIMESTAMPS"}
    deploy = deployment_epoch(settings, session=session)
    if re < deploy:
        return {"ok": False, "reason": "PRE_EPOCH"}

    if entry_order_id is not None:
        dup = session.scalar(
            select(UpbitProfitabilityReentryEventEntity).where(
                UpbitProfitabilityReentryEventEntity.user_broker_account_id
                == int(user_broker_account_id),
                UpbitProfitabilityReentryEventEntity.entry_order_id
                == int(entry_order_id),
            )
        )
        if dup is not None:
            return {"ok": True, "duplicate": True, "event_id": int(dup.event_id)}

    delay = (re - pe).total_seconds()
    decisions = {
        vid: decide_reentry_block(
            variant_id=vid, delay_seconds=delay, context=context
        )
        for vid in LAB_C_VARIANTS
    }
    row = UpbitProfitabilityReentryEventEntity(
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=strategy_id,
        symbol=str(symbol).upper(),
        prior_exit_at=pe,
        prior_exit_binding_id=prior_exit_binding_id,
        reentry_at=re,
        reentry_delay_seconds=Decimal(str(round(delay, 3))),
        entry_order_id=entry_order_id,
        binding_id=binding_id,
        rule_version=RULE_VERSION,
        research_only=True,
        status=STATUS_PENDING_OUTCOME,
        variant_decisions_json=decisions,
        post_exit_returns_json={},
        meta_json={"lab": LAB_C, "label": RESEARCH_ONLY_LABEL, "context": context or {}},
    )
    session.add(row)
    session.flush()
    return {
        "ok": True,
        "event_id": int(row.event_id),
        "SHADOW_ONLY": True,
        "REAL_POLICY_CHANGED": False,
    }


def finalize_reentry_pnl(
    session: Session,
    *,
    binding_id: int,
    net_pnl: Decimal | None,
    fees: Decimal | None,
) -> dict[str, Any]:
    row = session.scalar(
        select(UpbitProfitabilityReentryEventEntity).where(
            UpbitProfitabilityReentryEventEntity.binding_id == int(binding_id)
        )
    )
    if row is None:
        return {"ok": False, "reason": "NOT_FOUND"}
    row.real_net_pnl = net_pnl
    row.real_fees = fees
    if row.status == STATUS_PENDING_OUTCOME:
        row.status = STATUS_COMPLETED
    session.flush()
    return {"ok": True}


# ---------- Summaries ----------


def summarize_profitability_lab(
    session: Session, *, user_broker_account_id: int = 1380
) -> dict[str, Any]:
    activated = deployment_epoch(session=session)
    cand_n = len(
        list(
            session.scalars(
                select(UpbitProfitabilityCandidateRefreshEntity).where(
                    UpbitProfitabilityCandidateRefreshEntity.user_broker_account_id
                    == int(user_broker_account_id)
                )
            )
        )
    )
    exit_n = len(
        list(
            session.scalars(
                select(UpbitProfitabilityExitEnrollmentEntity).where(
                    UpbitProfitabilityExitEnrollmentEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    UpbitProfitabilityExitEnrollmentEntity.status
                    != STATUS_PRE_EXISTING_EXCLUDED,
                )
            )
        )
    )
    re_n = len(
        list(
            session.scalars(
                select(UpbitProfitabilityReentryEventEntity).where(
                    UpbitProfitabilityReentryEventEntity.user_broker_account_id
                    == int(user_broker_account_id)
                )
            )
        )
    )
    return {
        "LAB_ID": LAB_ID,
        "SHADOW_ONLY": True,
        "FORWARD_ONLY": True,
        "REAL_POLICY_CHANGED": False,
        "AUTO_PROMOTION": AUTO_PROMOTION,
        "ACTIVATED_AT": activated.isoformat(),
        "SAMPLE_STATUS": {
            LAB_A: _readiness(
                cand_n,
                CANDIDATE_EARLY_REVIEW_N,
                CANDIDATE_PRIMARY_REVIEW_N,
                CANDIDATE_PROMOTION_REVIEW_N,
            ),
            LAB_B: _readiness(
                exit_n, EXIT_EARLY_REVIEW_N, EXIT_PRIMARY_REVIEW_N, EXIT_PROMOTION_REVIEW_N
            ),
            LAB_C: _readiness(
                re_n,
                REENTRY_EARLY_REVIEW_N,
                REENTRY_PRIMARY_REVIEW_N,
                REENTRY_PROMOTION_REVIEW_N,
            ),
        },
        "SAMPLE_N": {
            "CANDIDATE_REFRESH_N": cand_n,
            "EXIT_ENROLLMENT_N": exit_n,
            "REENTRY_EVENT_N": re_n,
        },
        "GATES": {
            LAB_A: {
                "EARLY": CANDIDATE_EARLY_REVIEW_N,
                "PRIMARY": CANDIDATE_PRIMARY_REVIEW_N,
                "PROMOTION": CANDIDATE_PROMOTION_REVIEW_N,
            },
            LAB_B: {
                "EARLY": EXIT_EARLY_REVIEW_N,
                "PRIMARY": EXIT_PRIMARY_REVIEW_N,
                "PROMOTION": EXIT_PROMOTION_REVIEW_N,
            },
            LAB_C: {
                "EARLY": REENTRY_EARLY_REVIEW_N,
                "PRIMARY": REENTRY_PRIMARY_REVIEW_N,
                "PROMOTION": REENTRY_PROMOTION_REVIEW_N,
            },
        },
        "VARIANT_LABELS": {
            **{f"A:{k}": v for k, v in LAB_A_LABELS.items()},
            **{f"B:{k}": v for k, v in LAB_B_LABELS.items()},
            **{f"C:{k}": v for k, v in LAB_C_LABELS.items()},
        },
        "CANDIDATES": summarize_candidates(session, user_broker_account_id=user_broker_account_id),
        "EXITS": summarize_exits(session, user_broker_account_id=user_broker_account_id),
        "REENTRY": summarize_reentry(session, user_broker_account_id=user_broker_account_id),
        "COMBINED_ESTIMATE": "INSUFFICIENT_DATA",
        "COMBINED_NOTE": "Need independent PRIMARY samples on all three labs before hypothetical combine",
    }


def summarize_candidates(
    session: Session, *, user_broker_account_id: int = 1380
) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(UpbitProfitabilityCandidateRefreshEntity).where(
                UpbitProfitabilityCandidateRefreshEntity.user_broker_account_id
                == int(user_broker_account_id),
                UpbitProfitabilityCandidateRefreshEntity.status == STATUS_COMPLETED,
            )
        )
    )
    out: dict[str, Any] = {}
    for vid in LAB_A_VARIANTS:
        rets = {m: [] for m in (10, 30, 60)}
        mfes: list[float] = []
        maes: list[float] = []
        pairs = {m: [] for m in (10, 30, 60)}
        n = 0
        for row in rows:
            ranks = list((row.rankings_json or {}).get(vid) or [])
            outcomes = dict(row.outcomes_json or {})
            for item in ranks[:10]:
                sym = str(item.get("symbol") or "").upper()
                oc = outcomes.get(sym) or {}
                sc = item.get("score")
                n += 1
                for m in (10, 30, 60):
                    r = (oc.get(f"{m}M") or {}).get("RETURN")
                    if r is not None:
                        rets[m].append(float(r))
                        if sc is not None:
                            pairs[m].append((float(sc), float(r)))
                mfe = (oc.get("30M") or {}).get("MFE")
                mae = (oc.get("30M") or {}).get("MAE")
                if mfe is not None:
                    mfes.append(float(mfe))
                if mae is not None:
                    maes.append(float(mae))
        out[vid] = {
            "LABEL": LAB_A_LABELS[vid],
            "OBSERVATION_N": len(rows),
            "SYMBOL_OBS_N": n,
            "AVG_RETURN_10M": _mean(rets[10]),
            "AVG_RETURN_30M": _mean(rets[30]),
            "AVG_RETURN_60M": _mean(rets[60]),
            "MEDIAN_RETURN_30M": (
                round(statistics.median(rets[30]), 4) if rets[30] else None
            ),
            "POSITIVE_RATE_10M": (
                round(sum(1 for x in rets[10] if x > 0) / len(rets[10]), 4)
                if rets[10]
                else None
            ),
            "POSITIVE_RATE_30M": (
                round(sum(1 for x in rets[30] if x > 0) / len(rets[30]), 4)
                if rets[30]
                else None
            ),
            "POSITIVE_RATE_60M": (
                round(sum(1 for x in rets[60] if x > 0) / len(rets[60]), 4)
                if rets[60]
                else None
            ),
            "AVG_MFE": _mean(mfes),
            "AVG_MAE": _mean(maes),
            "SCORE_RETURN_CORRELATION_10M": _corr(
                [a for a, _ in pairs[10]], [b for _, b in pairs[10]]
            ),
            "SCORE_RETURN_CORRELATION_30M": _corr(
                [a for a, _ in pairs[30]], [b for _, b in pairs[30]]
            ),
            "SCORE_RETURN_CORRELATION_60M": _corr(
                [a for a, _ in pairs[60]], [b for _, b in pairs[60]]
            ),
            "READINESS": _readiness(
                len(rows),
                CANDIDATE_EARLY_REVIEW_N,
                CANDIDATE_PRIMARY_REVIEW_N,
                CANDIDATE_PROMOTION_REVIEW_N,
            ),
        }
    # deltas vs A0
    base = out.get(VARIANT_A0) or {}
    for vid in LAB_A_VARIANTS:
        if vid == VARIANT_A0:
            out[vid]["DELTA_AVG_RETURN_30M"] = 0.0
            continue
        a = out[vid].get("AVG_RETURN_30M")
        b = base.get("AVG_RETURN_30M")
        out[vid]["DELTA_AVG_RETURN_30M"] = (
            round(a - b, 4) if a is not None and b is not None else None
        )
    return {
        "SHADOW_ONLY": True,
        "REAL_POLICY_CHANGED": False,
        "VARIANTS": out,
        "REFRESH_COMPLETED_N": len(rows),
    }


def summarize_exits(
    session: Session, *, user_broker_account_id: int = 1380
) -> dict[str, Any]:
    enrolls = list(
        session.scalars(
            select(UpbitProfitabilityExitEnrollmentEntity).where(
                UpbitProfitabilityExitEnrollmentEntity.user_broker_account_id
                == int(user_broker_account_id),
                UpbitProfitabilityExitEnrollmentEntity.status == STATUS_COMPLETED,
            )
        )
    )
    variants = list(
        session.scalars(
            select(UpbitProfitabilityExitVariantEntity).where(
                UpbitProfitabilityExitVariantEntity.status == STATUS_COMPLETED
            )
        )
    )
    by_binding = {int(e.binding_id): e for e in enrolls}
    out: dict[str, Any] = {}
    for vid in LAB_B_VARIANTS:
        grp = [
            v
            for v in variants
            if v.variant_id == vid and int(v.binding_id) in by_binding
        ]
        nets = [float(v.shadow_net_pnl) for v in grp if v.shadow_net_pnl is not None]
        deltas = [float(v.net_delta) for v in grp if v.net_delta is not None]
        holds = [
            float(v.shadow_holding_seconds)
            for v in grp
            if v.shadow_holding_seconds is not None
        ]
        lt30 = [h for h in holds if h < 30]
        out[vid] = {
            "LABEL": LAB_B_LABELS[vid],
            "N": len(grp),
            "SHADOW_NET": round(sum(nets), 4) if nets else None,
            "DELTA_NET": round(sum(deltas), 4) if deltas else None,
            "AVG_HOLD": round(statistics.mean(holds), 1) if holds else None,
            "MEDIAN_HOLD": round(statistics.median(holds), 1) if holds else None,
            "LT30_COUNT": len(lt30),
            "DEFER_TOTAL": sum(int(v.defer_count or 0) for v in grp),
            "READINESS": _readiness(
                len(grp), EXIT_EARLY_REVIEW_N, EXIT_PRIMARY_REVIEW_N, EXIT_PROMOTION_REVIEW_N
            ),
        }
    return {
        "SHADOW_ONLY": True,
        "REAL_POLICY_CHANGED": False,
        "ENROLLMENT_COMPLETED_N": len(enrolls),
        "VARIANTS": out,
    }


def summarize_reentry(
    session: Session, *, user_broker_account_id: int = 1380
) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(UpbitProfitabilityReentryEventEntity).where(
                UpbitProfitabilityReentryEventEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        )
    )
    out: dict[str, Any] = {}
    triggered_n = 0
    diverged_n = 0
    for r in rows:
        decisions = dict(r.variant_decisions_json or {})
        c2 = dict(decisions.get(VARIANT_C2) or {})
        c3 = dict(decisions.get(VARIANT_C3) or {})
        # trigger = C2 또는 C3가 block 검토 대상 (delay 경계 포함 전체 paired)
        triggered_n += 1
        if bool(c2.get("WOULD_BLOCK")) != bool(c3.get("WOULD_BLOCK")):
            diverged_n += 1
    for vid in LAB_C_VARIANTS:
        blocked = []
        for r in rows:
            dec = dict((r.variant_decisions_json or {}).get(vid) or {})
            if dec.get("WOULD_BLOCK"):
                blocked.append(r)
        avoided_loss = 0.0
        avoided_fees = 0.0
        missed_profit = 0.0
        for r in blocked:
            net = float(r.real_net_pnl) if r.real_net_pnl is not None else None
            fee = float(r.real_fees) if r.real_fees is not None else 0.0
            if net is None:
                continue
            if net < 0:
                avoided_loss += -net
                avoided_fees += fee
            else:
                missed_profit += net
        out[vid] = {
            "LABEL": LAB_C_LABELS[vid],
            "N": len(rows),
            "BLOCKED_N": len(blocked),
            "AVOIDED_LOSS": round(avoided_loss, 4),
            "AVOIDED_FEES": round(avoided_fees, 4),
            "MISSED_PROFIT": round(missed_profit, 4),
            "NET_ESTIMATED_DELTA": round(
                avoided_loss + avoided_fees - missed_profit, 4
            ),
            "READINESS": _readiness(
                len(rows),
                REENTRY_EARLY_REVIEW_N,
                REENTRY_PRIMARY_REVIEW_N,
                REENTRY_PROMOTION_REVIEW_N,
            ),
        }
    return {
        "SHADOW_ONLY": True,
        "REAL_POLICY_CHANGED": False,
        "EVENT_N": len(rows),
        "TRIGGERED_N": triggered_n,
        "DIVERGED_DECISION_N": diverged_n,
        "VARIANTS": out,
    }


def reconcile_exit_finalizations(
    session: Session,
    *,
    user_broker_account_id: int = 1380,
    limit: int = 100,
) -> dict[str, Any]:
    """CLOSED upbit binding + ACTIVE enrollment → deterministic baseline finalize.

    Fabrication 금지 — closed_at/exit order/entry order가 있을 때만.
    """

    from sqlalchemy import text

    rows = list(
        session.execute(
            text(
                """
                SELECT e.enrollment_id, e.binding_id, e.entry_order_id, e.entry_at,
                       e.entry_price, e.entry_quantity,
                       b.closed_at, b.meta_json, b.opened_at
                FROM operation.upbit_profitability_exit_enrollment e
                JOIN operation.upbit_strategy_position_binding b
                  ON b.binding_id = e.binding_id
                WHERE e.user_broker_account_id = :uba
                  AND e.status = :active
                  AND e.real_exit_at IS NULL
                  AND b.status = 'CLOSED'
                  AND b.closed_at IS NOT NULL
                ORDER BY b.closed_at ASC
                LIMIT :lim
                """
            ),
            {
                "uba": int(user_broker_account_id),
                "active": STATUS_ACTIVE,
                "lim": int(limit),
            },
        ).mappings()
    )
    reconciled = 0
    skipped = 0
    for r in rows:
        meta = dict(r["meta_json"] or {})
        exit_reason = str(meta.get("exit_reason") or "UNKNOWN")
        exit_oid = meta.get("exit_order_id")
        exit_px = None
        fees = Decimal("0")
        qty = float(r["entry_quantity"] or 0)
        buy_notional = 0.0
        sell_notional = 0.0
        entry_px = float(r["entry_price"]) if r["entry_price"] is not None else None
        if r["entry_order_id"] is not None:
            from stock_platform.order.entities import TradingOrderEntity

            buy = session.get(TradingOrderEntity, int(r["entry_order_id"]))
            if buy is not None:
                if buy.average_fill_price is not None:
                    entry_px = float(buy.average_fill_price)
                if qty <= 0:
                    qty = float(buy.filled_quantity or 0)
                buy_notional = float(buy.filled_amount or 0)
                if buy_notional <= 0 and entry_px and qty:
                    buy_notional = entry_px * qty
        if exit_oid is not None:
            from stock_platform.order.entities import TradingOrderEntity

            sell = session.get(TradingOrderEntity, int(exit_oid))
            if sell is not None and sell.average_fill_price is not None:
                exit_px = Decimal(str(sell.average_fill_price))
                if qty <= 0:
                    qty = float(sell.filled_quantity or 0)
                sell_notional = float(sell.filled_amount or 0)
                if sell_notional <= 0 and exit_px is not None and qty > 0:
                    sell_notional = float(exit_px) * qty
        if exit_px is None and entry_px is None:
            skipped += 1
            continue
        fee_rate = 0.0005
        fees_f = (buy_notional + sell_notional) * fee_rate
        if exit_px is not None and entry_px is not None and qty > 0:
            gross_f = (float(exit_px) - entry_px) * qty
        elif sell_notional > 0 and buy_notional > 0:
            gross_f = sell_notional - buy_notional
        else:
            # exit price 불명이면 fee만 확정 가능한 경우 skip (fabrication 금지)
            skipped += 1
            continue
        net_f = gross_f - fees_f
        closed = r["closed_at"]
        hold_s = None
        if r["opened_at"] is not None and closed is not None:
            hold_s = (closed - r["opened_at"]).total_seconds()
        try:
            with session.begin_nested():
                finalize_exit_on_close(
                    session,
                    binding_id=int(r["binding_id"]),
                    exit_at=closed,
                    exit_price=exit_px,
                    exit_reason=exit_reason,
                    gross_pnl=Decimal(str(round(gross_f, 4))),
                    fees=Decimal(str(round(fees_f, 4))),
                    net_pnl=Decimal(str(round(net_f, 4))),
                    hold_seconds=hold_s,
                )
            reconciled += 1
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
    session.flush()
    return {
        "ok": True,
        "RECONCILED_N": reconciled,
        "SKIPPED_N": skipped,
        "CANDIDATE_N": len(rows),
        "SHADOW_ONLY": True,
        "REAL_POLICY_CHANGED": False,
    }
