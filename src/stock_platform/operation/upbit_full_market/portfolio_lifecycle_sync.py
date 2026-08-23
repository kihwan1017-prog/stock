"""Portfolio slot ↔ local AUTO order lifecycle 동기화 (generic, idempotent)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_full_market.constants import (
    BINDING_STATUS_CLOSED,
    BINDING_STATUS_OPEN,
    SLOT_ENTRY_PENDING,
    SLOT_EXIT_PENDING,
    SLOT_OPEN,
    is_full_market_portfolio,
)
from stock_platform.operation.upbit_full_market.entities import (
    UpbitPositionSlotEntity,
    UpbitStrategyPositionBindingEntity,
)
from stock_platform.operation.upbit_full_market.service import (
    UpbitFullMarketAssignmentService,
)
from stock_platform.order.models import OrderStatus

logger = structlog.get_logger(__name__)

_FILLED_STATUSES = frozenset({OrderStatus.FILLED.value, "FILLED"})
_OPEN_ORDER_STATUSES = frozenset(
    {
        OrderStatus.CREATED.value,
        OrderStatus.PENDING.value,
        OrderStatus.SENT.value,
        OrderStatus.ACCEPTED.value,
        OrderStatus.PARTIALLY_FILLED.value,
        "CREATED",
        "PENDING",
        "SENT",
        "ACCEPTED",
        "PARTIAL",
        "PARTIALLY_FILLED",
        "PARTIAL_FILLED",
        "SUBMITTED",
        "OPEN",
        "WORKING",
        "CANCEL_REQUESTED",
        "REPLACE_REQUESTED",
    }
)
_EXIT_SIGNAL_REASONS = frozenset(
    {
        "MA_DEAD_CROSS",
        "STOP_LOSS",
        "TAKE_PROFIT",
        "TRAILING_STOP",
        "STRATEGY_SIGNAL",
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _order_status(order: Any) -> str:
    return str(getattr(order, "status_code", "") or "").upper()


def _order_meta(order: Any) -> dict[str, Any]:
    raw = getattr(order, "metadata_payload", None) or {}
    return dict(raw) if isinstance(raw, dict) else {}


def _is_filled(order: Any) -> bool:
    return _order_status(order) in _FILLED_STATUSES


def _is_open(order: Any) -> bool:
    return _order_status(order) in _OPEN_ORDER_STATUSES


def _order_source(order: Any) -> str:
    direct = str(getattr(order, "order_source", "") or "").upper()
    if direct:
        return direct
    return str(_order_meta(order).get("order_source") or "").upper()


def _is_portfolio_entry_buy(order: Any) -> bool:
    if str(getattr(order, "side_code", "") or "").upper() != "BUY":
        return False
    if _order_source(order) != "AUTO":
        return False
    reason = str(_order_meta(order).get("signal_reason") or "").upper()
    return "PORTFOLIO" in reason or reason.endswith("_ENTRY")


def _is_auto_exit_sell(order: Any) -> bool:
    if str(getattr(order, "side_code", "") or "").upper() != "SELL":
        return False
    if _order_source(order) != "AUTO":
        return False
    meta = _order_meta(order)
    reason = str(
        meta.get("signal_reason") or meta.get("exit_reason") or ""
    ).upper()
    if reason in _EXIT_SIGNAL_REASONS:
        return True
    # AUTO SELL during managed slot lifecycle
    return bool(reason)


def _load_auto_orders(
    session: Session, *, user_broker_account_id: int, symbol: str
) -> list[Any]:
    from stock_platform.order.entities import TradingOrderEntity

    rows = list(
        session.scalars(
            select(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id
                == int(user_broker_account_id),
                TradingOrderEntity.symbol == str(symbol).upper(),
                TradingOrderEntity.broker_code == "UPBIT",
            )
            .order_by(TradingOrderEntity.order_id.asc())
        )
    )
    return [o for o in rows if _order_source(o) == "AUTO"]


def _open_upbit_binding(
    session: Session, *, user_broker_account_id: int, symbol: str
) -> UpbitStrategyPositionBindingEntity | None:
    return session.scalar(
        select(UpbitStrategyPositionBindingEntity)
        .where(
            UpbitStrategyPositionBindingEntity.user_broker_account_id
            == int(user_broker_account_id),
            UpbitStrategyPositionBindingEntity.symbol == str(symbol).upper(),
            UpbitStrategyPositionBindingEntity.status == BINDING_STATUS_OPEN,
        )
        .order_by(UpbitStrategyPositionBindingEntity.opened_at.desc())
        .limit(1)
    )


def link_entry_order_to_pending_slot(
    session: Session,
    *,
    user_broker_account_id: int,
    order_id: int,
    symbol: str,
    actor: str = "system",
) -> dict[str, Any]:
    """BUY 주문 생성 직후 ENTRY_PENDING slot에 entry_order_id 연결."""

    uba_id = int(user_broker_account_id)
    sym = str(symbol or "").upper()
    oid = int(order_id)
    assignment = UpbitFullMarketAssignmentService(session).get_or_create(uba_id)
    if not is_full_market_portfolio(assignment.mode):
        return {"ok": False, "reason": "MODE_NOT_PORTFOLIO", "linked": False}

    slot = session.scalar(
        select(UpbitPositionSlotEntity)
        .where(
            UpbitPositionSlotEntity.user_broker_account_id == uba_id,
            UpbitPositionSlotEntity.symbol == sym,
            UpbitPositionSlotEntity.status == SLOT_ENTRY_PENDING,
        )
        .with_for_update()
    )
    if slot is None:
        return {"ok": True, "linked": False, "reason": "NO_ENTRY_PENDING_SLOT"}
    if slot.entry_order_id is not None:
        return {
            "ok": True,
            "linked": False,
            "reason": "ALREADY_LINKED",
            "entry_order_id": int(slot.entry_order_id),
        }

    slot.entry_order_id = oid
    slot.version = int(slot.version or 1) + 1
    slot.updated_at = _now()
    session.flush()
    logger.info(
        "portfolio_entry_order_linked",
        uba_id=uba_id,
        symbol=sym,
        order_id=oid,
        slot_id=int(slot.slot_id),
        actor=str(actor)[:80],
    )
    return {
        "ok": True,
        "linked": True,
        "slot_id": int(slot.slot_id),
        "entry_order_id": oid,
    }


def reconcile_portfolio_slot_lifecycle(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Local AUTO order SoT 기준 portfolio slot/binding 상태 복원 (멱등)."""

    uba_id = int(user_broker_account_id)
    fm = UpbitFullMarketAssignmentService(session)
    assignment = fm.get_or_create(uba_id)
    if not is_full_market_portfolio(assignment.mode):
        return {"ok": False, "reason": "MODE_NOT_PORTFOLIO", "transitions": []}

    sym_filter = str(symbol).upper() if symbol else None
    q = select(UpbitPositionSlotEntity).where(
        UpbitPositionSlotEntity.user_broker_account_id == uba_id,
        UpbitPositionSlotEntity.status.in_(
            [SLOT_ENTRY_PENDING, SLOT_OPEN, SLOT_EXIT_PENDING]
        ),
    )
    if sym_filter:
        q = q.where(UpbitPositionSlotEntity.symbol == sym_filter)
    slots = list(session.scalars(q.with_for_update()))

    transitions: list[dict[str, Any]] = []
    for slot in slots:
        sym = str(slot.symbol or "").upper()
        if not sym:
            continue
        row = _reconcile_one_slot(
            session,
            slot=slot,
            assignment=assignment,
            fm=fm,
            orders=_load_auto_orders(session, user_broker_account_id=uba_id, symbol=sym),
            actor=actor,
        )
        if row:
            transitions.append(row)

    if transitions:
        session.flush()
        logger.info(
            "portfolio_slot_lifecycle_reconciled",
            uba_id=uba_id,
            transitions=len(transitions),
            actor=str(actor)[:80],
        )

    return {
        "ok": True,
        "uba_id": uba_id,
        "transitions": transitions,
        "changed": len(transitions) > 0,
        "orders_created": 0,
    }


def _pick_entry_buy(orders: list[Any], slot: UpbitPositionSlotEntity) -> Any | None:
    if slot.entry_order_id is not None:
        for o in orders:
            if int(o.order_id) == int(slot.entry_order_id):
                return o
    candidates = [o for o in orders if _is_portfolio_entry_buy(o)]
    if not candidates:
        # fallback: 첫 AUTO BUY (portfolio entry 직후 생성된 주문)
        candidates = [
            o
            for o in orders
            if str(getattr(o, "side_code", "") or "").upper() == "BUY"
        ]
    if not candidates:
        return None
    slot_ts = slot.updated_at or slot.created_at
    if slot_ts is not None:
        if slot_ts.tzinfo is None:
            slot_ts = slot_ts.replace(tzinfo=timezone.utc)
        after = [
            o
            for o in candidates
            if getattr(o, "created_at", None) is not None
            and (
                o.created_at.replace(tzinfo=timezone.utc)
                if o.created_at.tzinfo is None
                else o.created_at.astimezone(timezone.utc)
            )
            >= slot_ts.astimezone(timezone.utc)
        ]
        if after:
            candidates = after
    filled = [o for o in candidates if _is_filled(o)]
    if filled:
        return filled[-1]
    open_rows = [o for o in candidates if _is_open(o)]
    if open_rows:
        return open_rows[-1]
    return candidates[-1]


def _pick_exit_sell(orders: list[Any], *, entry_order_id: int | None) -> Any | None:
    sells = [o for o in orders if _is_auto_exit_sell(o)]
    if entry_order_id is not None:
        sells = [
            o
            for o in sells
            if int(getattr(o, "order_id", 0) or 0) > int(entry_order_id)
        ]
    if not sells:
        return None
    filled = [o for o in sells if _is_filled(o)]
    if filled:
        return filled[-1]
    open_rows = [o for o in sells if _is_open(o)]
    if open_rows:
        return open_rows[-1]
    return sells[-1]


def _reconcile_one_slot(
    session: Session,
    *,
    slot: UpbitPositionSlotEntity,
    assignment: Any,
    fm: UpbitFullMarketAssignmentService,
    orders: list[Any],
    actor: str,
) -> dict[str, Any] | None:
    prior_status = str(slot.status)
    sym = str(slot.symbol or "").upper()
    changes: list[str] = []

    entry_buy = _pick_entry_buy(orders, slot)
    if entry_buy is not None and slot.entry_order_id is None:
        slot.entry_order_id = int(entry_buy.order_id)
        slot.version = int(slot.version or 1) + 1
        changes.append("ENTRY_ORDER_LINKED")

    entry_order_id = (
        int(slot.entry_order_id) if slot.entry_order_id is not None else None
    )
    exit_sell = _pick_exit_sell(orders, entry_order_id=entry_order_id)

    binding = _open_upbit_binding(
        session, user_broker_account_id=int(slot.user_broker_account_id), symbol=sym
    )
    if binding is None and slot.position_binding_id is not None:
        binding = session.get(
            UpbitStrategyPositionBindingEntity, int(slot.position_binding_id)
        )
        if binding is not None and str(binding.status) != BINDING_STATUS_OPEN:
            binding = None

    # BUY FILLED → OPEN (+ Upbit binding)
    if entry_buy is not None and _is_filled(entry_buy):
        if prior_status == SLOT_ENTRY_PENDING or (
            prior_status == SLOT_OPEN and slot.position_binding_id is None
        ):
            eid = int(entry_buy.order_id)
            if binding is None:
                opened = fm.mark_position_open(
                    int(slot.user_broker_account_id),
                    symbol=sym,
                    entry_order_id=eid,
                    selection_id=slot.candidate_selection_id,
                    slot_id=int(slot.slot_id),
                )
                if opened.get("ok"):
                    changes.append("MARK_POSITION_OPEN")
                    binding = session.get(
                        UpbitStrategyPositionBindingEntity,
                        int(opened.get("binding_id") or 0),
                    )
                    try:
                        session.refresh(slot)
                    except Exception:  # noqa: BLE001
                        slot.status = SLOT_OPEN
                        slot.reserved_amount_krw = None
            else:
                slot.status = SLOT_OPEN
                slot.entry_order_id = eid
                slot.position_binding_id = int(binding.binding_id)
                slot.reserved_amount_krw = None
                slot.opened_at = slot.opened_at or _now()
                slot.version = int(slot.version or 1) + 1
                if binding.slot_id is None:
                    binding.slot_id = int(slot.slot_id)
                if binding.entry_order_id is None:
                    binding.entry_order_id = eid
                changes.append("SLOT_OPEN_SYNCED")

    # OPEN(또는 filled BUY 직후 ENTRY_PENDING) + open SELL → EXIT_PENDING
    if exit_sell is not None and _is_open(exit_sell):
        buy_ready = entry_buy is not None and _is_filled(entry_buy)
        if buy_ready and str(slot.status) in {SLOT_OPEN, SLOT_ENTRY_PENDING}:
            if str(slot.status) == SLOT_ENTRY_PENDING:
                slot.status = SLOT_OPEN
                slot.reserved_amount_krw = None
                if slot.entry_order_id is None and entry_buy is not None:
                    slot.entry_order_id = int(entry_buy.order_id)
            slot.status = SLOT_EXIT_PENDING
            slot.version = int(slot.version or 1) + 1
            changes.append("EXIT_PENDING")
            if binding is not None:
                meta = dict(binding.meta_json or {})
                meta["exit_order_id"] = int(exit_sell.order_id)
                exit_reason = str(
                    _order_meta(exit_sell).get("signal_reason") or ""
                ).upper()
                if exit_reason:
                    meta["exit_reason"] = exit_reason
                binding.meta_json = meta

    # FILLED SELL → CLOSED / slot release
    if exit_sell is not None and _is_filled(exit_sell):
        if str(slot.status) in {SLOT_OPEN, SLOT_EXIT_PENDING, SLOT_ENTRY_PENDING}:
            closed = fm.mark_position_closed(
                int(slot.user_broker_account_id), symbol=sym
            )
            if closed.get("ok"):
                changes.append("POSITION_CLOSED")
                # mark_position_closed → COOLDOWN; entry_order_id는 cooldown tick에서 정리
                refreshed = session.get(UpbitPositionSlotEntity, int(slot.slot_id))
                if refreshed is not None:
                    refreshed.entry_order_id = eid if (eid := entry_order_id) else refreshed.entry_order_id
                    meta_exit = int(exit_sell.order_id)
                    if binding is not None:
                        bmeta = dict(binding.meta_json or {})
                        bmeta["exit_order_id"] = meta_exit
                        binding.meta_json = bmeta

    if not changes:
        return None

    return {
        "slot_id": int(slot.slot_id),
        "symbol": sym,
        "from": prior_status,
        "to": str(slot.status),
        "changes": changes,
        "entry_order_id": (
            int(slot.entry_order_id) if slot.entry_order_id is not None else None
        ),
        "exit_order_id": (
            int(exit_sell.order_id) if exit_sell is not None else None
        ),
    }
