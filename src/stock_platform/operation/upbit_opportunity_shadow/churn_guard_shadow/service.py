"""Churn Guard Shadow service — episode lifecycle, fail-open, REAL 무영향."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.constants import (
    CHURN_GUARD_VERSION,
    COUNTERFACTUAL_PAUSE_KEYS,
    COUNTERFACTUAL_PAUSE_SECONDS,
    DETECTION_PROFILES,
    FAMILY,
    LOOKBACK_CLOSED_RTS,
    LOOKBACK_SECONDS,
    MODE,
    OWNERSHIP_AMBIGUOUS,
    OWNERSHIP_MANUAL,
    OWNERSHIP_STRATEGY,
    OWNERSHIP_UNKNOWN,
    REAL_BLOCK_ENABLED,
    REALERT_MIN_SECONDS,
    REALERT_NET_LOSS_DELTA_KRW,
    RESOLVE_IDLE_SECONDS,
    RESOLVE_MIN_WINNING_RTS,
    SEVERITY_RANK,
    STATUS_ACTIVE,
    STATUS_RESOLVED,
    THRESHOLD_VARIANTS,
)
from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.detector import (
    evaluate_round_trips,
)
from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.entities import (
    UpbitChurnGuardShadowEpisodeEntity,
)
from stock_platform.risk_engine.strategy_owned_entities import (
    StrategyPositionBindingEntity,
)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001
        return None


def status_payload() -> dict[str, Any]:
    return {
        "mode": MODE,
        "version": CHURN_GUARD_VERSION,
        "family": FAMILY,
        "real_block_enabled": REAL_BLOCK_ENABLED,
        "detector_available": True,
        "detection_profiles": list(DETECTION_PROFILES),
        "threshold_variants": list(THRESHOLD_VARIANTS),
        "counterfactual_pause_variants": list(COUNTERFACTUAL_PAUSE_KEYS),
    }


def _rt_from_binding(
    session: Session,
    *,
    binding: StrategyPositionBindingEntity,
    previous_closed_at: datetime | None,
) -> dict[str, Any] | None:
    ownership = str(getattr(binding, "ownership_code", "") or "").upper()
    if ownership == OWNERSHIP_MANUAL:
        return None
    if ownership in {OWNERSHIP_UNKNOWN, OWNERSHIP_AMBIGUOUS}:
        return {
            "ownership_code": ownership,
            "unknown": True,
            "binding_id": int(binding.binding_id),
        }

    meta = dict(binding.meta_json or {})
    entry_oid = getattr(binding, "entry_order_id", None)
    exit_oid = meta.get("exit_order_id")
    exit_reason = str(meta.get("exit_reason") or "UNKNOWN")
    entry_px = float(binding.entry_price) if binding.entry_price is not None else None
    exit_px = None
    qty = float(binding.owned_quantity or 0)
    buy_notional = 0.0
    sell_notional = 0.0
    fees = float(binding.fees or 0)
    gross = float(binding.realized_pnl or 0)
    net = gross

    try:
        from stock_platform.order.entities import TradingOrderEntity

        if entry_oid is not None:
            buy = session.get(TradingOrderEntity, int(entry_oid))
            if buy is not None:
                if getattr(buy, "average_fill_price", None) is not None:
                    entry_px = float(buy.average_fill_price)
                qty = float(getattr(buy, "filled_quantity", None) or qty or 0)
                buy_notional = float(getattr(buy, "filled_amount", None) or 0)
                if buy_notional <= 0 and entry_px and qty:
                    buy_notional = entry_px * qty
                mp = getattr(buy, "metadata_payload", None) or {}
                if isinstance(mp, dict) and mp.get("exit_reason"):
                    pass
        if exit_oid is not None:
            sell = session.get(TradingOrderEntity, int(exit_oid))
            if sell is not None:
                if getattr(sell, "average_fill_price", None) is not None:
                    exit_px = float(sell.average_fill_price)
                sell_notional = float(getattr(sell, "filled_amount", None) or 0)
                if sell_notional <= 0 and exit_px and qty:
                    sell_notional = exit_px * qty
                mp = getattr(sell, "metadata_payload", None) or {}
                if isinstance(mp, dict):
                    exit_reason = str(
                        mp.get("exit_reason")
                        or mp.get("signal_reason")
                        or exit_reason
                    )
        fee_rate = 0.0005
        est_fees = (buy_notional + sell_notional) * fee_rate
        if fees <= 0:
            fees = est_fees
        if entry_px is not None and exit_px is not None and qty > 0:
            gross = (exit_px - entry_px) * qty
            net = gross - fees
        elif buy_notional > 0 and sell_notional > 0:
            gross = sell_notional - buy_notional
            net = gross - fees
    except Exception:  # noqa: BLE001
        pass

    opened = _as_utc(binding.opened_at)
    closed = _as_utc(binding.closed_at)
    hold = None
    if opened and closed:
        hold = max(0.0, (closed - opened).total_seconds())
    reentry_delay = None
    if previous_closed_at is not None and opened is not None:
        reentry_delay = max(
            0.0, (opened - _as_utc(previous_closed_at)).total_seconds()  # type: ignore[arg-type]
        )

    overlap = int(meta.get("overlapping_entry_skip_count") or 0)
    c3 = None
    for key in ("c3_shadow_decision", "SHADOW_DECISION"):
        if meta.get(key):
            c3 = str(meta.get(key))
            break
    # profitability reentry event lookup (best-effort)
    try:
        from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.entities import (
            UpbitProfitabilityReentryEventEntity,
        )

        ev = session.scalar(
            select(UpbitProfitabilityReentryEventEntity)
            .where(
                UpbitProfitabilityReentryEventEntity.binding_id
                == int(binding.binding_id)
            )
            .order_by(UpbitProfitabilityReentryEventEntity.event_id.desc())
            .limit(1)
        )
        if ev is not None:
            vd = dict(ev.variant_decisions_json or {})
            c3_block = vd.get("C3") or {}
            if isinstance(c3_block, dict):
                c3 = str(
                    c3_block.get("SHADOW_DECISION")
                    or (
                        "BLOCK"
                        if c3_block.get("WOULD_BLOCK")
                        else "ALLOW"
                        if "WOULD_BLOCK" in c3_block
                        else c3
                    )
                    or c3
                    or "UNKNOWN"
                )
    except Exception:  # noqa: BLE001
        pass

    return {
        "binding_id": int(binding.binding_id),
        "ownership_code": ownership or OWNERSHIP_STRATEGY,
        "opened_at": opened.isoformat() if opened else None,
        "closed_at": closed.isoformat() if closed else None,
        "entry_order_id": int(entry_oid) if entry_oid is not None else None,
        "exit_order_id": int(exit_oid) if exit_oid is not None else None,
        "entry_price": entry_px,
        "exit_price": exit_px,
        "quantity": qty,
        "gross_pnl": round(gross, 4),
        "fees": round(fees, 4),
        "net_pnl": round(net, 4),
        "turnover_krw": round(buy_notional + sell_notional, 4),
        "exit_reason": exit_reason,
        "holding_seconds": hold,
        "reentry_delay_seconds": reentry_delay,
        "overlapping_skip_count": overlap,
        "c3_shadow_decision": c3,
    }


def load_recent_round_trips(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    limit: int = LOOKBACK_CLOSED_RTS,
    lookback_seconds: int = LOOKBACK_SECONDS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """STRATEGY_OWNED RTs + UNKNOWN 분리."""

    uba = int(user_broker_account_id)
    sym = str(symbol).upper()
    since = _now() - timedelta(seconds=int(lookback_seconds))
    rows = list(
        session.scalars(
            select(StrategyPositionBindingEntity)
            .where(
                StrategyPositionBindingEntity.user_broker_account_id == uba,
                StrategyPositionBindingEntity.symbol == sym,
                StrategyPositionBindingEntity.status == "CLOSED",
                StrategyPositionBindingEntity.closed_at.is_not(None),
                StrategyPositionBindingEntity.closed_at >= since,
            )
            .order_by(StrategyPositionBindingEntity.closed_at.asc())
            .limit(max(limit * 2, limit))
        )
    )
    # keep last `limit` chronological
    if len(rows) > limit:
        rows = rows[-limit:]

    rts: list[dict[str, Any]] = []
    unknowns: list[dict[str, Any]] = []
    prev_closed: datetime | None = None
    for b in rows:
        item = _rt_from_binding(session, binding=b, previous_closed_at=prev_closed)
        if item is None:
            continue
        if item.get("unknown"):
            unknowns.append(item)
        else:
            rts.append(item)
            prev_closed = _as_utc(b.closed_at)
    return rts, unknowns


def _empty_counterfactual() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in COUNTERFACTUAL_PAUSE_KEYS:
        out[key] = {
            "avoided_reentries": None,
            "avoided_loss": None,
            "missed_profit": None,
            "status": "PENDING_FORWARD",
        }
    return out


def _update_counterfactual(
    *,
    detected_at: datetime,
    round_trips: list[dict[str, Any]],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """자연 outcome 기반 — 미래가격 조작 금지."""

    base = existing or _empty_counterfactual()
    det = _as_utc(detected_at) or _now()
    for key, secs in COUNTERFACTUAL_PAUSE_SECONDS.items():
        window_end = det + timedelta(seconds=int(secs))
        subsequent = []
        for r in round_trips:
            closed_s = r.get("closed_at")
            if not closed_s:
                continue
            try:
                closed = datetime.fromisoformat(str(closed_s).replace("Z", "+00:00"))
            except Exception:  # noqa: BLE001
                continue
            closed = _as_utc(closed)
            if closed is None:
                continue
            if det < closed <= window_end:
                subsequent.append(r)
        if not subsequent:
            base[key] = {
                "avoided_reentries": 0,
                "avoided_loss": 0.0,
                "missed_profit": 0.0,
                "status": "PENDING_FORWARD"
                if _now() < window_end
                else "OBSERVED_EMPTY",
            }
            continue
        avoided_loss = 0.0
        missed_profit = 0.0
        for r in subsequent:
            net = float(r.get("net_pnl") or 0)
            if net < 0:
                avoided_loss += abs(net)
            elif net > 0:
                missed_profit += net
        base[key] = {
            "avoided_reentries": len(subsequent),
            "avoided_loss": round(avoided_loss, 4),
            "missed_profit": round(missed_profit, 4),
            "status": "OBSERVED",
        }
    return base


def _should_realert(
    episode: UpbitChurnGuardShadowEpisodeEntity,
    *,
    new_severity: str,
    new_primary: str,
    new_secondaries: list[str],
    new_net: float,
    now: datetime,
) -> bool:
    last = _as_utc(episode.last_alert_at)
    if last is None:
        return True
    elapsed = (now - last).total_seconds()
    old_rank = SEVERITY_RANK.get(str(episode.last_alert_severity or episode.severity), 0)
    new_rank = SEVERITY_RANK.get(new_severity, 0)
    if new_rank > old_rank:
        return True
    old_secs = set(episode.secondary_classifications_json or [])
    if new_primary != episode.primary_classification:
        return True
    if any(s not in old_secs for s in new_secondaries):
        return True
    old_net = float(episode.net_pnl or 0)
    if new_net <= old_net - REALERT_NET_LOSS_DELTA_KRW:
        return True
    if elapsed >= REALERT_MIN_SECONDS and new_rank >= old_rank:
        # 동일 상태 반복 억제 — 시간만으로는 재알림하지 않음
        return False
    return False


def evaluate_on_binding_closed(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    binding_id: int | None = None,
    cycle_still_active: bool = False,
) -> dict[str, Any]:
    """CLOSED binding 직후 incremental evaluation — REAL 무영향."""

    uba = int(user_broker_account_id)
    sym = str(symbol).upper()
    rts, unknowns = load_recent_round_trips(
        session, user_broker_account_id=uba, symbol=sym
    )
    if unknowns and not rts:
        return {
            "ok": True,
            "observed": False,
            "reason": "UNKNOWN_OWNERSHIP_ONLY",
            "unknown_count": len(unknowns),
        }
    if not rts:
        return {"ok": True, "observed": False, "reason": "NO_STRATEGY_RTS"}

    # OPEN 동일 symbol 있으면 cycle 지속으로 간주
    if not cycle_still_active:
        open_n = session.scalar(
            select(StrategyPositionBindingEntity.binding_id)
            .where(
                StrategyPositionBindingEntity.user_broker_account_id == uba,
                StrategyPositionBindingEntity.symbol == sym,
                StrategyPositionBindingEntity.status == "OPEN",
                StrategyPositionBindingEntity.ownership_code == OWNERSHIP_STRATEGY,
            )
            .limit(1)
        )
        cycle_still_active = open_n is not None

    evaluated = evaluate_round_trips(rts, cycle_still_active=cycle_still_active)
    signals = evaluated["signals"]
    now = _now()

    active = session.scalar(
        select(UpbitChurnGuardShadowEpisodeEntity)
        .where(
            UpbitChurnGuardShadowEpisodeEntity.user_broker_account_id == uba,
            UpbitChurnGuardShadowEpisodeEntity.symbol == sym,
            UpbitChurnGuardShadowEpisodeEntity.status == STATUS_ACTIVE,
        )
        .order_by(UpbitChurnGuardShadowEpisodeEntity.event_id.desc())
        .limit(1)
    )

    # Resolve path: hysteresis — 연속 손실 끊김 + idle
    if active is not None and not evaluated["should_alert"]:
        consec = int(signals.get("consecutive_losing_round_trips") or 0)
        idle = (
            now - (_as_utc(active.last_observed_at) or now)
        ).total_seconds() >= RESOLVE_IDLE_SECONDS
        recent_wins = sum(1 for r in rts[-RESOLVE_MIN_WINNING_RTS :] if float(r.get("net_pnl") or 0) > 0)
        if consec == 0 and idle and recent_wins >= RESOLVE_MIN_WINNING_RTS:
            active.status = STATUS_RESOLVED
            active.resolved_at = now
            active.resolution_note = "HYSTERESIS_IDLE_AND_RECOVERY"
            active.last_observed_at = now
            detail = dict(active.detail_json or {})
            detail["resolved_signals"] = signals
            active.detail_json = detail
            flag_modified(active, "detail_json")
            session.flush()
            return {
                "ok": True,
                "observed": True,
                "resolved": True,
                "event_id": int(active.event_id),
            }
        # evidence 약해도 ACTIVE 유지 시 last_observed만 갱신하지 않음 (spam 방지)
        return {
            "ok": True,
            "observed": True,
            "active_unchanged": True,
            "event_id": int(active.event_id),
            "should_alert": False,
        }

    if not evaluated["should_alert"] and active is None:
        return {
            "ok": True,
            "observed": True,
            "should_alert": False,
            "severity": evaluated["severity"],
            "primary_classification": evaluated["primary_classification"],
            "threshold_variants": evaluated["threshold_variants"],
            "signals": signals,
        }

    # Create / update ACTIVE episode
    alerted = False
    if active is None:
        first_at = now
        try:
            first_at = datetime.fromisoformat(
                str(rts[0].get("closed_at")).replace("Z", "+00:00")
            )
            first_at = _as_utc(first_at) or now
        except Exception:  # noqa: BLE001
            first_at = now
        cf = _update_counterfactual(detected_at=now, round_trips=rts)
        active = UpbitChurnGuardShadowEpisodeEntity(
            user_broker_account_id=uba,
            symbol=sym,
            severity=str(evaluated["severity"]),
            primary_classification=str(evaluated["primary_classification"]),
            secondary_classifications_json=list(
                evaluated["secondary_classifications"]
            ),
            detected_at=now,
            first_observed_at=first_at,
            last_observed_at=now,
            round_trip_count=int(signals.get("same_symbol_round_trips") or 0),
            loss_count=int(signals.get("loss_count") or 0),
            consecutive_loss_count=int(
                signals.get("consecutive_losing_round_trips") or 0
            ),
            gross_pnl=_dec(signals.get("gross_pnl")),
            fees=_dec(signals.get("estimated_or_actual_fee")),
            net_pnl=_dec(signals.get("net_pnl")),
            reentry_count=int(signals.get("reentry_count_10m") or 0),
            min_reentry_seconds=_dec(signals.get("min_reentry_seconds")),
            dominant_exit_reason=signals.get("dominant_exit_reason"),
            telegram_dedupe_key=f"CHURN:{uba}:{sym}:NEW",
            detail_json={
                "signals": signals,
                "profiles": evaluated["profiles"],
                "threshold_variants": evaluated["threshold_variants"],
                "timeline": rts,
                "unknown_ownership": unknowns,
                "counterfactual": cf,
                "binding_id": binding_id,
                "mode": MODE,
                "real_block_enabled": False,
            },
        )
        session.add(active)
        session.flush()
        alerted = True
    else:
        new_sev = str(evaluated["severity"])
        new_primary = str(evaluated["primary_classification"])
        new_secs = list(evaluated["secondary_classifications"])
        new_net = float(signals.get("net_pnl") or 0)
        alerted = _should_realert(
            active,
            new_severity=new_sev,
            new_primary=new_primary,
            new_secondaries=new_secs,
            new_net=new_net,
            now=now,
        )
        active.severity = new_sev
        active.primary_classification = new_primary
        active.secondary_classifications_json = new_secs
        active.last_observed_at = now
        active.round_trip_count = int(signals.get("same_symbol_round_trips") or 0)
        active.loss_count = int(signals.get("loss_count") or 0)
        active.consecutive_loss_count = int(
            signals.get("consecutive_losing_round_trips") or 0
        )
        active.gross_pnl = _dec(signals.get("gross_pnl"))
        active.fees = _dec(signals.get("estimated_or_actual_fee"))
        active.net_pnl = _dec(signals.get("net_pnl"))
        active.reentry_count = int(signals.get("reentry_count_10m") or 0)
        active.min_reentry_seconds = _dec(signals.get("min_reentry_seconds"))
        active.dominant_exit_reason = signals.get("dominant_exit_reason")
        detail = dict(active.detail_json or {})
        detail["signals"] = signals
        detail["profiles"] = evaluated["profiles"]
        detail["threshold_variants"] = evaluated["threshold_variants"]
        detail["timeline"] = rts
        detail["unknown_ownership"] = unknowns
        detail["counterfactual"] = _update_counterfactual(
            detected_at=_as_utc(active.detected_at) or now,
            round_trips=rts,
            existing=dict(detail.get("counterfactual") or {}),
        )
        detail["binding_id"] = binding_id
        active.detail_json = detail
        flag_modified(active, "detail_json")
        flag_modified(active, "secondary_classifications_json")
        session.flush()

    telegram_sent = False
    if alerted:
        try:
            from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.telegram import (
                emit_churn_guard_alert,
            )

            telegram_sent = bool(
                emit_churn_guard_alert(session, episode=active, force=False)
            )
            if telegram_sent:
                active.last_alert_at = now
                active.last_alert_severity = active.severity
                active.telegram_dedupe_key = (
                    f"CHURN:{uba}:{sym}:{int(active.event_id)}:{active.severity}"
                )
                session.flush()
        except Exception:  # noqa: BLE001
            # fail-open — trading 계속
            telegram_sent = False

    return {
        "ok": True,
        "observed": True,
        "should_alert": True,
        "alerted": alerted,
        "telegram_sent": telegram_sent,
        "event_id": int(active.event_id),
        "severity": active.severity,
        "primary_classification": active.primary_classification,
        "threshold_variants": evaluated["threshold_variants"],
        "signals": signals,
        "real_block_enabled": False,
        "mode": MODE,
    }


def list_episodes(
    session: Session,
    *,
    user_broker_account_id: int,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    uba = int(user_broker_account_id)
    q = select(UpbitChurnGuardShadowEpisodeEntity).where(
        UpbitChurnGuardShadowEpisodeEntity.user_broker_account_id == uba
    )
    if status:
        q = q.where(UpbitChurnGuardShadowEpisodeEntity.status == str(status).upper())
    rows = list(
        session.scalars(
            q.order_by(UpbitChurnGuardShadowEpisodeEntity.last_observed_at.desc()).limit(
                max(1, min(int(limit), 200))
            )
        )
    )
    active_rows = list(
        session.scalars(
            select(UpbitChurnGuardShadowEpisodeEntity).where(
                UpbitChurnGuardShadowEpisodeEntity.user_broker_account_id == uba,
                UpbitChurnGuardShadowEpisodeEntity.status == STATUS_ACTIVE,
            )
        )
    )
    return {
        **status_payload(),
        "active_count": len(active_rows),
        "episodes": [_episode_to_dict(r, include_detail=False) for r in rows],
    }


def get_episode(
    session: Session, *, event_id: int, user_broker_account_id: int | None = None
) -> dict[str, Any] | None:
    row = session.get(UpbitChurnGuardShadowEpisodeEntity, int(event_id))
    if row is None:
        return None
    if user_broker_account_id is not None and int(row.user_broker_account_id) != int(
        user_broker_account_id
    ):
        return None
    return _episode_to_dict(row, include_detail=True)


def _episode_to_dict(
    row: UpbitChurnGuardShadowEpisodeEntity, *, include_detail: bool
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "event_id": int(row.event_id),
        "user_broker_account_id": int(row.user_broker_account_id),
        "symbol": row.symbol,
        "status": row.status,
        "severity": row.severity,
        "primary_classification": row.primary_classification,
        "secondary_classifications": list(row.secondary_classifications_json or []),
        "detected_at": row.detected_at.isoformat() if row.detected_at else None,
        "first_observed_at": (
            row.first_observed_at.isoformat() if row.first_observed_at else None
        ),
        "last_observed_at": (
            row.last_observed_at.isoformat() if row.last_observed_at else None
        ),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "round_trip_count": int(row.round_trip_count or 0),
        "loss_count": int(row.loss_count or 0),
        "consecutive_loss_count": int(row.consecutive_loss_count or 0),
        "gross_pnl": float(row.gross_pnl) if row.gross_pnl is not None else None,
        "fees": float(row.fees) if row.fees is not None else None,
        "net_pnl": float(row.net_pnl) if row.net_pnl is not None else None,
        "reentry_count": int(row.reentry_count or 0),
        "min_reentry_seconds": (
            float(row.min_reentry_seconds)
            if row.min_reentry_seconds is not None
            else None
        ),
        "dominant_exit_reason": row.dominant_exit_reason,
        "mode": row.mode,
        "real_block_enabled": bool(row.real_block_enabled),
        "rule_version": row.rule_version,
        "notice_ko": "현재는 감시/경고 전용이며 자동 매매를 차단하지 않습니다.",
    }
    if include_detail:
        out["detail"] = dict(row.detail_json or {})
        out["resolution_note"] = row.resolution_note
        out["last_alert_at"] = (
            row.last_alert_at.isoformat() if row.last_alert_at else None
        )
    return out
