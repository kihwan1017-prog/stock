"""Exit Order Recovery Shadow Lab — enroll/tick/pair/summarize (fail-open)."""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.constants import (
    ACTION_MARKET_FALLBACK,
    ACTION_NO_ACTION,
    ACTION_REPRICE_BEST_BID,
    ALL_VARIANTS,
    COHORT_HISTORICAL_CONTEXT,
    COHORT_PRIMARY_FORWARD,
    EARLY_REVIEW_N,
    EST_TAKER_FEE_RATE,
    EVIDENCE_HIGH,
    EVIDENCE_LOW,
    EVIDENCE_MEDIUM,
    FEATURE_DEPLOY_EPOCH,
    FEATURE_DEPLOY_EPOCH_SOURCE,
    FEATURE_KEY,
    LAB_ID,
    PRIMARY_REVIEW_N,
    PROMOTION_REVIEW_N,
    R1_TRIGGER_AGE_SECONDS,
    R2_TRIGGER_AGE_SECONDS,
    R3_TRIGGER_AGE_SECONDS,
    R4_INCLUDED,
    RULE_VERSION,
    STATUS_ACTIVE,
    STATUS_PAIRED,
    STATUS_TRIGGERED,
    STATUS_UNRESOLVED,
    VARIANT_R0,
    VARIANT_R1,
    VARIANT_R2,
    VARIANT_R3,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.entities import (
    UpbitExitOrderRecoveryShadowObservationEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.epoch import (
    get_or_create_feature_epoch,
)
from stock_platform.order.entities import TradingOrderEntity

logger = structlog.get_logger(__name__)
ZERO = Decimal("0")
OPEN_STATUSES = frozenset(
    {
        "CREATED",
        "PENDING",
        "SUBMITTING",
        "SENT",
        "ACCEPTED",
        "PARTIALLY_FILLED",
        "REMOTE_LOOKUP_PENDING",
    }
)
TERMINAL_STATUSES = frozenset(
    {"FILLED", "CANCELLED", "REJECTED", "FAILED", "EXPIRED"}
)


def shadow_enabled(settings: Any | None = None) -> bool:
    try:
        from stock_platform.common.settings import get_settings

        s = settings or get_settings()
        return bool(getattr(s, "upbit_exit_order_recovery_shadow_enabled", True))
    except Exception:  # noqa: BLE001
        return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def _fetch_book(symbol: str) -> dict[str, Decimal | None]:
    """Public ticker/orderbook — research only, no private broker."""
    out: dict[str, Decimal | None] = {
        "trade_price": None,
        "best_bid": None,
        "best_ask": None,
    }
    try:
        with urllib.request.urlopen(
            f"https://api.upbit.com/v1/ticker?markets={symbol}", timeout=8
        ) as resp:
            data = json.loads(resp.read().decode())[0]
            out["trade_price"] = _dec(data.get("trade_price"))
    except Exception:  # noqa: BLE001
        pass
    try:
        with urllib.request.urlopen(
            f"https://api.upbit.com/v1/orderbook?markets={symbol}", timeout=8
        ) as resp:
            book = json.loads(resp.read().decode())[0]
            units = book.get("orderbook_units") or []
            if units:
                out["best_bid"] = _dec(units[0].get("bid_price"))
                out["best_ask"] = _dec(units[0].get("ask_price"))
    except Exception:  # noqa: BLE001
        pass
    return out


def _is_auto_strategy_owned_exit(order: TradingOrderEntity, session: Session) -> bool:
    if str(order.side_code or "").upper() != "SELL":
        return False
    if str(order.broker_code or "").upper() != "UPBIT":
        return False
    meta = order.metadata_payload or {}
    source = str(meta.get("source") or "").upper()
    order_source = str(
        meta.get("order_source")
        or getattr(order, "order_source", None)
        or ""
    ).upper()
    # MANUAL / UNKNOWN / BUY 제외
    if order_source == "MANUAL" or source in {"MANUAL", "USER", "UNKNOWN"}:
        return False
    if str(order.side_code or "").upper() == "BUY":
        return False
    # EXIT monitor / AUTO exit / MA dead cross auto sell
    ok_source = source in {
        "POSITION_EXIT_MONITOR",
        "REALTIME_SIGNAL",
        "SAFE_EXIT_RECOVERY",
    } or order_source in {"EXIT", "AUTO"}
    if not ok_source:
        # exit_reason alone is insufficient without ownership provenance
        return False
    if order.strategy_id is None and meta.get("strategy_id") is None:
        return False
    binding_id = meta.get("binding_id")
    if binding_id is None:
        return True  # strategy-linked exit without binding still AUTO
    try:
        from sqlalchemy import text

        row = session.execute(
            text(
                """
                SELECT ownership_code FROM operation.strategy_position_binding
                WHERE binding_id = :b
                """
            ),
            {"b": int(binding_id)},
        ).first()
        if row is None:
            return True
        ownership = str(row[0] or "").upper()
        if ownership in {"MANUAL", "UNKNOWN", ""}:
            return False
        return ownership == "STRATEGY_OWNED"
    except Exception:  # noqa: BLE001
        return True


def _trigger_age_for_variant(variant: str) -> float | None:
    if variant == VARIANT_R1:
        return R1_TRIGGER_AGE_SECONDS
    if variant == VARIANT_R2:
        return R2_TRIGGER_AGE_SECONDS
    if variant == VARIANT_R3:
        return R3_TRIGGER_AGE_SECONDS
    return None


def _action_for_variant(variant: str) -> str:
    if variant == VARIANT_R1:
        return ACTION_REPRICE_BEST_BID
    if variant == VARIANT_R2:
        return ACTION_REPRICE_BEST_BID
    if variant == VARIANT_R3:
        return ACTION_MARKET_FALLBACK
    return ACTION_NO_ACTION


def enroll_exit_order(
    session: Session,
    *,
    order_id: int,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    """REAL exit order 1건에 대해 R0–R3 observation 생성 (idempotent)."""

    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}

    order = session.get(TradingOrderEntity, int(order_id))
    if order is None:
        return {"ok": False, "reason": "ORDER_MISSING"}
    uba = int(user_broker_account_id or order.user_broker_account_id or 0)
    if uba <= 0:
        return {"ok": False, "reason": "UBA_MISSING"}
    if not _is_auto_strategy_owned_exit(order, session):
        return {"ok": False, "reason": "NOT_AUTO_STRATEGY_OWNED_EXIT"}

    epoch_at, epoch_src = get_or_create_feature_epoch(
        session,
        feature_key=FEATURE_KEY,
        seed_epoch=FEATURE_DEPLOY_EPOCH,
        seed_source=FEATURE_DEPLOY_EPOCH_SOURCE,
    )
    created = _ensure_aware(order.created_at) or _now()
    if created < _ensure_aware(epoch_at):  # type: ignore[arg-type]
        cohort = COHORT_HISTORICAL_CONTEXT
    else:
        cohort = COHORT_PRIMARY_FORWARD

    meta = order.metadata_payload or {}
    enrolled = 0
    skipped = 0
    for variant in ALL_VARIANTS:
        existing = session.scalar(
            select(UpbitExitOrderRecoveryShadowObservationEntity).where(
                UpbitExitOrderRecoveryShadowObservationEntity.user_broker_account_id
                == uba,
                UpbitExitOrderRecoveryShadowObservationEntity.variant == variant,
                UpbitExitOrderRecoveryShadowObservationEntity.real_order_id
                == int(order_id),
            )
        )
        if existing is not None:
            skipped += 1
            continue
        row = UpbitExitOrderRecoveryShadowObservationEntity(
            user_broker_account_id=uba,
            variant=variant,
            cohort=cohort,
            symbol=str(order.symbol),
            strategy_id=(
                int(order.strategy_id)
                if order.strategy_id is not None
                else (
                    int(meta["strategy_id"])
                    if meta.get("strategy_id") is not None
                    else None
                )
            ),
            binding_id=(
                int(meta["binding_id"]) if meta.get("binding_id") is not None else None
            ),
            real_order_id=int(order_id),
            broker_uuid=str(order.broker_order_id) if order.broker_order_id else None,
            exit_reason=str(meta.get("exit_reason") or "") or None,
            real_order_type=str(order.order_type_code or "") or None,
            real_limit_price=_dec(order.order_price),
            real_created_at=created,
            enrolled_at=_now(),
            status=STATUS_ACTIVE,
            shadow_action=ACTION_NO_ACTION,
            research_only=True,
            rule_version=RULE_VERSION,
            meta_json={
                "lab_id": LAB_ID,
                "epoch_source": epoch_src,
                "order_source": meta.get("order_source") or meta.get("source"),
            },
        )
        session.add(row)
        enrolled += 1
    session.flush()
    return {
        "ok": True,
        "enrolled": enrolled,
        "skipped": skipped,
        "cohort": cohort,
        "order_id": int(order_id),
        "REAL_POLICY_CHANGED": False,
        "SHADOW_ONLY": True,
    }


def _apply_trigger(
    row: UpbitExitOrderRecoveryShadowObservationEntity,
    *,
    age_sec: float,
    book: dict[str, Decimal | None],
    remaining: Decimal,
) -> None:
    variant = row.variant
    action = _action_for_variant(variant)
    bid = book.get("best_bid")
    ask = book.get("best_ask")
    trade = book.get("trade_price")
    row.shadow_trigger_at = _now()
    row.shadow_trigger_age_seconds = Decimal(str(round(age_sec, 3)))
    row.market_price_at_trigger = trade
    row.best_bid_at_trigger = bid
    row.best_ask_at_trigger = ask
    row.remaining_qty_at_trigger = remaining
    row.shadow_action = action
    row.status = STATUS_TRIGGERED
    if action == ACTION_REPRICE_BEST_BID:
        # risk/reference = best bid (canonical executable sell reference)
        row.shadow_reference_price = bid or trade
    elif action == ACTION_MARKET_FALLBACK:
        # 962a502 semantics: broker price=None; risk_unit = trade/reference
        row.shadow_reference_price = trade or bid
        meta = dict(row.meta_json or {})
        meta["broker_price_semantics"] = "UPBIT_MARKET_SELL_VOLUME_ONLY"
        meta["risk_unit_price_source"] = "TRADE_OR_BID_AT_TRIGGER"
        row.meta_json = meta


def _try_shadow_fill(
    row: UpbitExitOrderRecoveryShadowObservationEntity,
    *,
    trade_price: Decimal | None,
) -> None:
    if row.status not in {STATUS_TRIGGERED, STATUS_ACTIVE}:
        return
    if row.variant == VARIANT_R0:
        return
    if row.shadow_action == ACTION_NO_ACTION:
        return
    if trade_price is None or trade_price <= ZERO:
        return
    ref = row.shadow_reference_price
    if row.shadow_action == ACTION_MARKET_FALLBACK:
        # first observed trade after trigger → HIGH fill estimate
        if row.shadow_trigger_at is None:
            return
        row.shadow_fill_status = "EST_FILLED"
        row.shadow_estimated_fill_price = trade_price
        trig = _ensure_aware(row.shadow_trigger_at)
        row.shadow_time_to_fill_seconds = Decimal(
            str(max(0.0, (_now() - trig).total_seconds()))  # type: ignore[operator]
        )
        if ref and ref > ZERO:
            slip = (ref - trade_price) / ref * Decimal("10000")
            row.shadow_slippage_bps = slip
        qty = row.remaining_qty_at_trigger or ZERO
        notional = qty * trade_price
        row.shadow_incremental_cost = (notional * Decimal(str(EST_TAKER_FEE_RATE))).quantize(
            Decimal("0.00000001")
        )
        row.evidence_quality = EVIDENCE_HIGH
        return
    if row.shadow_action == ACTION_REPRICE_BEST_BID and ref and ref > ZERO:
        # SELL limit @ bid: trade at/below bid is executable evidence
        if trade_price <= ref:
            row.shadow_fill_status = "EST_FILLED"
            row.shadow_estimated_fill_price = trade_price
            trig = _ensure_aware(row.shadow_trigger_at)
            if trig is not None:
                row.shadow_time_to_fill_seconds = Decimal(
                    str(max(0.0, (_now() - trig).total_seconds()))
                )
            slip = (ref - trade_price) / ref * Decimal("10000")
            row.shadow_slippage_bps = slip
            qty = row.remaining_qty_at_trigger or ZERO
            notional = qty * trade_price
            row.shadow_incremental_cost = (
                notional * Decimal(str(EST_TAKER_FEE_RATE))
            ).quantize(Decimal("0.00000001"))
            # exact hit on bid → MEDIUM; deeper → HIGH
            row.evidence_quality = (
                EVIDENCE_HIGH if trade_price < ref else EVIDENCE_MEDIUM
            )


def _pair_real_terminal(
    session: Session,
    row: UpbitExitOrderRecoveryShadowObservationEntity,
    order: TradingOrderEntity,
) -> None:
    status = str(order.status_code or "").upper()
    if status not in TERMINAL_STATUSES:
        return
    term_at = (
        _ensure_aware(order.filled_at)
        or _ensure_aware(order.cancelled_at)
        or _ensure_aware(order.updated_at)
        or _now()
    )
    created = _ensure_aware(row.real_created_at) or _ensure_aware(order.created_at)
    row.real_terminal_at = term_at
    row.real_terminal_state = status
    row.real_fill_price = _dec(order.average_fill_price) or _dec(order.order_price)
    row.real_filled_qty = _dec(order.filled_quantity) or ZERO
    if created and term_at:
        row.real_time_to_fill_seconds = Decimal(
            str(max(0.0, (term_at - created).total_seconds()))
        )
    # R0 pairs immediately on terminal
    if row.variant == VARIANT_R0:
        row.status = STATUS_PAIRED
        row.shadow_action = ACTION_NO_ACTION
        row.evidence_quality = EVIDENCE_HIGH
        return
    # triggered variants: keep shadow estimate; mark paired
    if row.status == STATUS_TRIGGERED and row.shadow_fill_status is None:
        # unresolved shadow fill — keep NULL, mark paired on real terminal
        row.evidence_quality = row.evidence_quality or EVIDENCE_LOW
    if row.status in {STATUS_TRIGGERED, STATUS_ACTIVE}:
        row.status = STATUS_PAIRED


def tick_active_observations(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    """Age trigger + terminal pairing + shadow fill evidence (no REAL cancel)."""

    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED", "REAL_TRADING_BLOCKED": False}

    try:
        q = select(UpbitExitOrderRecoveryShadowObservationEntity).where(
            UpbitExitOrderRecoveryShadowObservationEntity.status.in_(
                [STATUS_ACTIVE, STATUS_TRIGGERED]
            ),
            UpbitExitOrderRecoveryShadowObservationEntity.cohort
            == COHORT_PRIMARY_FORWARD,
        )
        if user_broker_account_id is not None:
            q = q.where(
                UpbitExitOrderRecoveryShadowObservationEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        rows = list(session.scalars(q).all())
        triggered = 0
        paired = 0
        books: dict[str, dict[str, Decimal | None]] = {}
        for row in rows:
            order = session.get(TradingOrderEntity, int(row.real_order_id))
            if order is None:
                continue
            # update broker uuid if arrived
            if order.broker_order_id and not row.broker_uuid:
                row.broker_uuid = str(order.broker_order_id)
            status = str(order.status_code or "").upper()
            if status in TERMINAL_STATUSES:
                _pair_real_terminal(session, row, order)
                if row.status == STATUS_PAIRED:
                    paired += 1
                continue

            remaining = _dec(order.remaining_quantity) or ZERO
            if remaining <= ZERO and status in OPEN_STATUSES:
                remaining = (_dec(order.order_quantity) or ZERO) - (
                    _dec(order.filled_quantity) or ZERO
                )

            created = _ensure_aware(row.real_created_at) or _ensure_aware(
                order.created_at
            )
            enrolled = _ensure_aware(row.enrolled_at) or created
            if created is None or enrolled is None:
                continue
            # REAL 주문 age (metrics) — trigger는 enrolled 이후만 (과거 가상 trigger 금지)
            real_age = (_now() - created).total_seconds()
            shadow_age = (_now() - enrolled).total_seconds()

            # MAE/MFE while waiting (SELL: adverse = price rise)
            sym = row.symbol
            if sym not in books:
                books[sym] = _fetch_book(sym)
            book = books[sym]
            trade = book.get("trade_price")
            limit_px = row.real_limit_price
            if trade and limit_px and limit_px > ZERO:
                move = (trade - limit_px) / limit_px
                # adverse for SELL waiting = upside move
                if row.mae_while_waiting is None or move > (row.mae_while_waiting or ZERO):
                    if move > ZERO:
                        row.mae_while_waiting = move
                        row.max_adverse_move_while_waiting = move
                if row.mfe_while_waiting is None or move < (row.mfe_while_waiting or ZERO):
                    if move < ZERO:
                        row.mfe_while_waiting = move

            if row.status == STATUS_ACTIVE and row.variant != VARIANT_R0:
                need = _trigger_age_for_variant(row.variant)
                # enrolled 이후 경과만 인정 — Lab 활성화 전 대기분에 대한 소급 trigger 금지
                if need is not None and shadow_age >= need and remaining > ZERO:
                    if status in OPEN_STATUSES:
                        _apply_trigger(
                            row,
                            age_sec=real_age,
                            book=book,
                            remaining=remaining,
                        )
                        triggered += 1

            if row.status == STATUS_TRIGGERED:
                _try_shadow_fill(row, trade_price=trade)

        session.flush()
        return {
            "ok": True,
            "active_rows": len(rows),
            "triggered": triggered,
            "paired": paired,
            "REAL_TRADING_BLOCKED": False,
            "SHADOW_ONLY": True,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("exit_order_recovery_shadow_tick_failed", error=str(exc)[:200])
        return {
            "ok": False,
            "error": str(exc)[:200],
            "REAL_TRADING_BLOCKED": False,
        }


def scan_and_enroll_open_exits(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    """Tick helper: enroll new open AUTO exits after epoch (no historical backfill triggers)."""

    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        epoch_at, _ = get_or_create_feature_epoch(
            session,
            feature_key=FEATURE_KEY,
            seed_epoch=FEATURE_DEPLOY_EPOCH,
            seed_source=FEATURE_DEPLOY_EPOCH_SOURCE,
        )
        q = select(TradingOrderEntity).where(
            TradingOrderEntity.broker_code == "UPBIT",
            TradingOrderEntity.side_code == "SELL",
            TradingOrderEntity.status_code.in_(list(OPEN_STATUSES)),
        )
        if user_broker_account_id is not None:
            q = q.where(
                TradingOrderEntity.user_broker_account_id == int(user_broker_account_id)
            )
        enrolled = 0
        for order in session.scalars(q).all():
            created = _ensure_aware(order.created_at)
            # only enroll; historical get HISTORICAL_CONTEXT_ONLY without fake triggers
            if created is None:
                continue
            res = enroll_exit_order(
                session,
                order_id=int(order.order_id),
                user_broker_account_id=(
                    int(order.user_broker_account_id)
                    if order.user_broker_account_id
                    else None
                ),
            )
            if res.get("ok") and int(res.get("enrolled") or 0) > 0:
                enrolled += int(res["enrolled"])
        return {"ok": True, "enrolled_rows": enrolled, "epoch_at": epoch_at.isoformat()}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "exit_order_recovery_shadow_scan_failed", error=str(exc)[:200]
        )
        return {"ok": False, "error": str(exc)[:200], "REAL_TRADING_BLOCKED": False}


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def summarize_exit_order_recovery_lab(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    epoch_at, epoch_src = get_or_create_feature_epoch(
        session,
        feature_key=FEATURE_KEY,
        seed_epoch=FEATURE_DEPLOY_EPOCH,
        seed_source=FEATURE_DEPLOY_EPOCH_SOURCE,
    )
    q = select(UpbitExitOrderRecoveryShadowObservationEntity).where(
        UpbitExitOrderRecoveryShadowObservationEntity.cohort
        == COHORT_PRIMARY_FORWARD,
    )
    if user_broker_account_id is not None:
        q = q.where(
            UpbitExitOrderRecoveryShadowObservationEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    rows = list(session.scalars(q).all())
    variants: dict[str, Any] = {}
    for v in ALL_VARIANTS:
        vrows = [r for r in rows if r.variant == v]
        paired = [
            r
            for r in vrows
            if r.status == STATUS_PAIRED
            and (r.evidence_quality or "") in {EVIDENCE_HIGH, EVIDENCE_MEDIUM, ""}
        ]
        # R0 always high when paired
        if v == VARIANT_R0:
            paired = [r for r in vrows if r.status == STATUS_PAIRED]
        valid = [
            r
            for r in paired
            if r.evidence_quality in {EVIDENCE_HIGH, EVIDENCE_MEDIUM, None}
            or v == VARIANT_R0
        ]
        real_ttf = [
            float(r.real_time_to_fill_seconds)
            for r in valid
            if r.real_time_to_fill_seconds is not None
            and r.real_terminal_state == "FILLED"
        ]
        shadow_ttf = [
            float(r.shadow_time_to_fill_seconds)
            for r in valid
            if r.shadow_time_to_fill_seconds is not None
            and r.shadow_fill_status == "EST_FILLED"
        ]
        long30 = sum(
            1
            for r in vrows
            if r.real_time_to_fill_seconds is not None
            and float(r.real_time_to_fill_seconds) >= 1800
        )
        long60 = sum(
            1
            for r in vrows
            if r.real_time_to_fill_seconds is not None
            and float(r.real_time_to_fill_seconds) >= 3600
        )
        long90 = sum(
            1
            for r in vrows
            if r.real_time_to_fill_seconds is not None
            and float(r.real_time_to_fill_seconds) >= 5400
        )
        variants[v] = {
            "TOTAL_ENROLLED": len(vrows),
            "TRIGGERED_COUNT": sum(
                1
                for r in vrows
                if r.status in {STATUS_TRIGGERED, STATUS_PAIRED}
                and r.shadow_action != ACTION_NO_ACTION
            ),
            "VALID_PAIRED_N": len(valid),
            "UNRESOLVED_COUNT": sum(
                1 for r in vrows if r.status in {STATUS_ACTIVE, STATUS_TRIGGERED, STATUS_UNRESOLVED}
            ),
            "REAL_AVG_TIME_TO_FILL": (
                sum(real_ttf) / len(real_ttf) if real_ttf else None
            ),
            "REAL_MEDIAN_TIME_TO_FILL": _median(real_ttf),
            "SHADOW_AVG_TIME_TO_FILL": (
                sum(shadow_ttf) / len(shadow_ttf) if shadow_ttf else None
            ),
            "SHADOW_MEDIAN_TIME_TO_FILL": _median(shadow_ttf),
            "REPRICE_COUNT": sum(
                1 for r in vrows if r.shadow_action == ACTION_REPRICE_BEST_BID
            ),
            "MARKET_FALLBACK_COUNT": sum(
                1 for r in vrows if r.shadow_action == ACTION_MARKET_FALLBACK
            ),
            "LONG_WAIT_GT_30M": long30,
            "LONG_WAIT_GT_60M": long60,
            "LONG_WAIT_GT_90M": long90,
            "REAL_FILL_RATE": (
                sum(1 for r in valid if r.real_terminal_state == "FILLED") / len(valid)
                if valid
                else None
            ),
            "SHADOW_EST_FILL_RATE": (
                sum(1 for r in valid if r.shadow_fill_status == "EST_FILLED")
                / len(valid)
                if valid and v != VARIANT_R0
                else None
            ),
        }

    valid_n = max(int(variants[v]["VALID_PAIRED_N"]) for v in ALL_VARIANTS)
    if valid_n < EARLY_REVIEW_N:
        readiness = "SAMPLE_PENDING"
    elif valid_n < PRIMARY_REVIEW_N:
        readiness = "EARLY_REVIEW"
    elif valid_n < PROMOTION_REVIEW_N:
        readiness = "PRIMARY_REVIEW"
    else:
        readiness = "PROMOTION_REVIEW_ELIGIBLE"

    return {
        "LAB_ID": LAB_ID,
        "RULE_VERSION": RULE_VERSION,
        "REAL_POLICY_CHANGED": False,
        "SHADOW_ONLY": True,
        "FORWARD_START_AT": epoch_at.isoformat(),
        "EPOCH_SOURCE": epoch_src,
        "R4_INCLUDED": R4_INCLUDED,
        "READINESS": readiness,
        "VALID_PAIRED_N_MAX": valid_n,
        "GATES": {
            "EARLY_REVIEW_N": EARLY_REVIEW_N,
            "PRIMARY_REVIEW_N": PRIMARY_REVIEW_N,
            "PROMOTION_REVIEW_N": PROMOTION_REVIEW_N,
        },
        "VARIANTS": variants,
        "VARIANT_LABELS": {
            VARIANT_R0: "R0 REAL baseline",
            VARIANT_R1: "R1 REPRICE_30M best-bid",
            VARIANT_R2: "R2 REPRICE_60M best-bid",
            VARIANT_R3: "R3 MARKET_FALLBACK_60M",
        },
        "EXIT_RECOVERY_SHADOW_ACTIVE": shadow_enabled(),
        "EXIT_RECOVERY_VARIANTS": list(ALL_VARIANTS),
        "AUTO_PROMOTION": False,
    }


def list_observations(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
    variant: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    q = select(UpbitExitOrderRecoveryShadowObservationEntity).order_by(
        UpbitExitOrderRecoveryShadowObservationEntity.observation_id.desc()
    )
    if user_broker_account_id is not None:
        q = q.where(
            UpbitExitOrderRecoveryShadowObservationEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    if variant:
        q = q.where(
            UpbitExitOrderRecoveryShadowObservationEntity.variant == str(variant)
        )
    rows = list(session.scalars(q.limit(max(1, min(int(limit), 500)))).all())
    items = []
    for r in rows:
        items.append(
            {
                "observation_id": r.observation_id,
                "variant": r.variant,
                "cohort": r.cohort,
                "symbol": r.symbol,
                "exit_reason": r.exit_reason,
                "real_order_id": r.real_order_id,
                "status": r.status,
                "shadow_action": r.shadow_action,
                "real_limit_price": (
                    None if r.real_limit_price is None else str(r.real_limit_price)
                ),
                "shadow_reference_price": (
                    None
                    if r.shadow_reference_price is None
                    else str(r.shadow_reference_price)
                ),
                "real_terminal_state": r.real_terminal_state,
                "real_fill_price": (
                    None if r.real_fill_price is None else str(r.real_fill_price)
                ),
                "shadow_fill_status": r.shadow_fill_status,
                "shadow_estimated_fill_price": (
                    None
                    if r.shadow_estimated_fill_price is None
                    else str(r.shadow_estimated_fill_price)
                ),
                "evidence_quality": r.evidence_quality,
                "real_time_to_fill_seconds": (
                    None
                    if r.real_time_to_fill_seconds is None
                    else float(r.real_time_to_fill_seconds)
                ),
                "shadow_time_to_fill_seconds": (
                    None
                    if r.shadow_time_to_fill_seconds is None
                    else float(r.shadow_time_to_fill_seconds)
                ),
                "enrolled_at": r.enrolled_at.isoformat() if r.enrolled_at else None,
            }
        )
    return {
        "REAL_POLICY_CHANGED": False,
        "SHADOW_ONLY": True,
        "count": len(items),
        "items": items,
    }


def compare_variants(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    summary = summarize_exit_order_recovery_lab(
        session, user_broker_account_id=user_broker_account_id
    )
    return {
        "REAL_POLICY_CHANGED": False,
        "SHADOW_ONLY": True,
        "comparison": summary.get("VARIANTS"),
        "readiness": summary.get("READINESS"),
        "FORWARD_START_AT": summary.get("FORWARD_START_AT"),
    }
