"""Portfolio slot ↔ local AUTO order lifecycle 동기화 (generic, idempotent)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_full_market.constants import (
    BINDING_STATUS_CLOSED,
    BINDING_STATUS_OPEN,
    SLOT_EMPTY,
    SLOT_ENTRY_PENDING,
    SLOT_EXIT_PENDING,
    SLOT_OPEN,
    SLOT_WAITING_SIGNAL,
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


_TERMINAL_ZERO_FILL_STATUSES = frozenset(
    {
        "CANCELLED",
        "CANCELED",
        "FAILED",
        "REJECTED",
        "EXPIRED",
    }
)


def _filled_qty(order: Any) -> float:
    try:
        return float(getattr(order, "filled_quantity", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_terminal_zero_fill(order: Any) -> bool:
    """체결 없는 종료 BUY — ENTRY_PENDING 슬롯 해제 대상."""
    if _filled_qty(order) > 0:
        return False
    return _order_status(order) in _TERMINAL_ZERO_FILL_STATUSES


def _release_entry_pending_slot(slot: UpbitPositionSlotEntity) -> None:
    """ENTRY_PENDING → EMPTY (주문/히스토리 삭제 없음)."""
    slot.status = SLOT_EMPTY
    slot.symbol = None
    slot.candidate_selection_id = None
    slot.scanner_run_id = None
    slot.ai_analysis_id = None
    slot.entry_order_id = None
    slot.position_binding_id = None
    slot.reserved_amount_krw = None
    slot.allocated_amount_krw = None
    slot.opened_at = None
    slot.closed_at = None
    slot.cooldown_until = None
    slot.version = int(slot.version or 1) + 1
    slot.updated_at = _now()



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
    meta = _order_meta(order)
    src = str(meta.get("source") or "").upper()
    o_src = _order_source(order)
    reason = str(
        meta.get("signal_reason") or meta.get("exit_reason") or ""
    ).upper()
    # POSITION_EXIT_MONITOR (order_source=EXIT) 포함
    if o_src == "EXIT" or src == "POSITION_EXIT_MONITOR":
        return True
    if o_src != "AUTO":
        return False
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
    # AUTO + EXIT(monitor) — protective exit도 slot reconcile SoT
    out: list[Any] = []
    for o in rows:
        src = _order_source(o)
        meta = _order_meta(o)
        if src == "AUTO":
            out.append(o)
        elif src == "EXIT" or str(meta.get("source") or "").upper() == (
            "POSITION_EXIT_MONITOR"
        ):
            out.append(o)
    return out


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
            [
                SLOT_ENTRY_PENDING,
                SLOT_OPEN,
                SLOT_EXIT_PENDING,
                SLOT_WAITING_SIGNAL,
            ]
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
        if str(slot.status) == SLOT_WAITING_SIGNAL:
            row = _reconcile_waiting_signal_slot(
                session,
                slot=slot,
                assignment=assignment,
                orders=_load_auto_orders(
                    session, user_broker_account_id=uba_id, symbol=sym
                ),
                actor=actor,
            )
        else:
            row = _reconcile_one_slot(
                session,
                slot=slot,
                assignment=assignment,
                fm=fm,
                orders=_load_auto_orders(
                    session, user_broker_account_id=uba_id, symbol=sym
                ),
                actor=actor,
            )
        if row:
            transitions.append(row)

    # OPEN 포지션이 없으면 assignment.current_symbol 잔여 정리
    open_syms = list(
        session.scalars(
            select(UpbitPositionSlotEntity.symbol).where(
                UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                UpbitPositionSlotEntity.status.in_(
                    [SLOT_OPEN, SLOT_EXIT_PENDING, SLOT_ENTRY_PENDING]
                ),
                UpbitPositionSlotEntity.symbol.is_not(None),
            )
        )
    )
    if not open_syms and assignment.current_symbol:
        # WAITING_SIGNAL만 남아도 "현재 심볼"은 청산 후 잔여일 수 있음
        still_waiting = session.scalar(
            select(func.count())
            .select_from(UpbitPositionSlotEntity)
            .where(
                UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                UpbitPositionSlotEntity.status == SLOT_WAITING_SIGNAL,
                UpbitPositionSlotEntity.symbol
                == str(assignment.current_symbol).upper(),
            )
        )
        if int(still_waiting or 0) == 0:
            prior = str(assignment.current_symbol)
            assignment.current_symbol = None
            assignment.updated_at = _now()
            transitions.append(
                {
                    "slot_id": None,
                    "symbol": prior,
                    "from": "ASSIGNMENT_CURRENT_SYMBOL",
                    "to": "CLEARED",
                    "changes": ["CURRENT_SYMBOL_CLEARED_NO_OPEN"],
                }
            )

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


def _reconcile_waiting_signal_slot(
    session: Session,
    *,
    slot: UpbitPositionSlotEntity,
    assignment: Any,
    orders: list[Any],
    actor: str,
) -> dict[str, Any] | None:
    """WAITING_SIGNAL 잔여 정리 — max-wait 초과·무포지션만 EMPTY로 복귀.

    유효 후보 대기는 유지. 임의 replacement 금지.
    """

    from stock_platform.operation.upbit_full_market.constants import (
        DEFAULT_PORTFOLIO_CANDIDATE_MAX_WAIT_SECONDS,
    )
    from stock_platform.operation.upbit_full_market.entities import (
        UpbitPortfolioPolicyEntity,
    )

    prior = str(slot.status)
    sym = str(slot.symbol or "").upper()
    if not sym:
        return None

    open_binding = _open_upbit_binding(
        session,
        user_broker_account_id=int(slot.user_broker_account_id),
        symbol=sym,
    )
    if open_binding is not None:
        return None

    open_orders = [o for o in orders if _is_open(o)]
    if open_orders:
        return None

    entry_buy = _pick_entry_buy(orders, slot)
    # 이미 ENTRY가 진행 중이면 WAITING 해제 금지
    if entry_buy is not None and (
        _is_open(entry_buy) or not _is_filled(entry_buy)
    ):
        return None

    policy = session.scalar(
        select(UpbitPortfolioPolicyEntity).where(
            UpbitPortfolioPolicyEntity.user_broker_account_id
            == int(slot.user_broker_account_id)
        )
    )
    max_wait = float(DEFAULT_PORTFOLIO_CANDIDATE_MAX_WAIT_SECONDS)
    if policy is not None:
        rg = dict(getattr(policy, "risk_group_policy_json", None) or {})
        try:
            max_wait = float(rg.get("candidate_max_wait_seconds") or max_wait)
        except (TypeError, ValueError):
            max_wait = float(DEFAULT_PORTFOLIO_CANDIDATE_MAX_WAIT_SECONDS)

    anchor = slot.updated_at or slot.created_at
    if anchor is None:
        return None
    a = anchor if anchor.tzinfo else anchor.replace(tzinfo=timezone.utc)
    age_sec = max(0.0, (_now() - a.astimezone(timezone.utc)).total_seconds())
    if age_sec < max_wait:
        return None

    slot.status = SLOT_EMPTY
    slot.symbol = None
    slot.candidate_selection_id = None
    slot.scanner_run_id = None
    slot.ai_analysis_id = None
    slot.entry_order_id = None
    slot.position_binding_id = None
    slot.reserved_amount_krw = None
    slot.allocated_amount_krw = None
    slot.opened_at = None
    slot.closed_at = None
    slot.cooldown_until = None
    slot.version = int(slot.version or 1) + 1
    slot.updated_at = _now()
    _ = (assignment, actor)
    return {
        "slot_id": int(slot.slot_id),
        "symbol": sym,
        "from": prior,
        "to": SLOT_EMPTY,
        "changes": ["WAITING_MAX_WAIT_EXPIRED"],
        "entry_order_id": None,
        "exit_order_id": None,
        "waiting_age_seconds": age_sec,
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

    # ENTRY_PENDING + zero-fill 종료 BUY → EMPTY (고착 방지)
    if prior_status == SLOT_ENTRY_PENDING and entry_buy is not None:
        if _is_terminal_zero_fill(entry_buy):
            _release_entry_pending_slot(slot)
            changes.append("ENTRY_PENDING_ZERO_FILL_RELEASED")
            return {
                "slot_id": int(slot.slot_id),
                "symbol": sym,
                "from": prior_status,
                "to": SLOT_EMPTY,
                "changes": changes,
                "entry_order_id": int(getattr(entry_buy, "order_id", 0) or 0) or None,
                "exit_order_id": None,
                "release_reason": _order_status(entry_buy),
            }

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

    # EXIT_PENDING + zero-fill 종료 SELL → OPEN 복귀 (보유 수량 유지, 청산 아님)
    open_exit_sells = [
        o for o in orders if _is_auto_exit_sell(o) and _is_open(o)
    ]
    if (
        str(slot.status) == SLOT_EXIT_PENDING
        and not open_exit_sells
        and exit_sell is not None
        and _is_terminal_zero_fill(exit_sell)
        and entry_buy is not None
        and _is_filled(entry_buy)
    ):
        slot.status = SLOT_OPEN
        slot.version = int(slot.version or 1) + 1
        slot.updated_at = _now()
        changes.append("EXIT_PENDING_CANCELLED_REOPEN")
        if binding is not None:
            bmeta = dict(binding.meta_json or {})
            # 취소된 exit 주문 참조만 정리 — binding/수량 삭제 금지
            if int(bmeta.get("exit_order_id") or 0) == int(exit_sell.order_id):
                bmeta.pop("exit_order_id", None)
                bmeta.pop("exit_reason", None)
                bmeta["last_cancelled_exit_order_id"] = int(exit_sell.order_id)
                binding.meta_json = bmeta

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
