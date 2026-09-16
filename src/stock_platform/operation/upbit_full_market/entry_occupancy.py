"""UPBIT AUTO same-symbol entry occupancy — fail-closed under admission lock.

REAL MA/Trailing/C3 policy unchanged. Research/shadow writes stay fail-open elsewhere.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_full_market.constants import (
    BINDING_STATUS_EXIT_PENDING,
    BINDING_STATUS_OPEN,
    SLOT_ENTRY_PENDING,
    SLOT_EXIT_PENDING,
    SLOT_OPEN,
)

# Canonical skip reasons (ops-readable)
REASON_ACTIVE_ENTRY_LIFECYCLE = "ENTRY_SKIPPED_ACTIVE_ENTRY_LIFECYCLE"
REASON_EXISTING_SYMBOL_EXPOSURE = "ENTRY_SKIPPED_EXISTING_SYMBOL_EXPOSURE"
REASON_PENDING_RECONCILIATION = "ENTRY_SKIPPED_PENDING_RECONCILIATION"

# Slot statuses that block a new AUTO BUY for the same symbol
OCCUPYING_SLOT_STATUSES = frozenset(
    {
        SLOT_ENTRY_PENDING,
        SLOT_OPEN,
        SLOT_EXIT_PENDING,
    }
)

# Binding statuses that block a new AUTO BUY
OCCUPYING_BINDING_STATUSES = frozenset(
    {
        BINDING_STATUS_OPEN,
        BINDING_STATUS_EXIT_PENDING,
    }
)

# Non-terminal AUTO order statuses (BUY or open SELL that implies exposure)
_NON_TERMINAL_ORDER_STATUSES = frozenset(
    {
        "CREATED",
        "QUEUED",
        "SUBMITTING",
        "SUBMITTED",
        "ACCEPTED",
        "PARTIAL",
        "PARTIALLY_FILLED",
        "PENDING_CANCEL",
        "CANCEL_REQUESTED",
        "AMBIGUOUS",
        "RECONCILING",
    }
)


def inspect_symbol_auto_occupancy(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
) -> dict[str, Any]:
    """동일 UBA+symbol AUTO occupancy 조회 (admission lock 안에서 호출).

    MANUAL-only 보유는 여기서 막지 않음 — SymbolOwnership / preexisting_holding이 담당.
    """

    uba_id = int(user_broker_account_id)
    sym = str(symbol or "").upper()
    if not sym:
        return {
            "occupied": False,
            "reason": None,
            "details": {"error": "SYMBOL_REQUIRED"},
        }

    from stock_platform.operation.upbit_full_market.entities import (
        UpbitPositionSlotEntity,
        UpbitStrategyPositionBindingEntity,
    )

    details: dict[str, Any] = {"symbol": sym, "uba_id": uba_id}

    # 1) Portfolio slots
    slot = session.scalar(
        select(UpbitPositionSlotEntity).where(
            UpbitPositionSlotEntity.user_broker_account_id == uba_id,
            UpbitPositionSlotEntity.symbol == sym,
            UpbitPositionSlotEntity.status.in_(tuple(OCCUPYING_SLOT_STATUSES)),
        )
    )
    if slot is not None:
        st = str(slot.status)
        details["slot_id"] = int(slot.slot_id)
        details["slot_status"] = st
        details["slot_entry_order_id"] = (
            int(slot.entry_order_id) if slot.entry_order_id is not None else None
        )
        if st == SLOT_ENTRY_PENDING and slot.entry_order_id is not None:
            reason = REASON_ACTIVE_ENTRY_LIFECYCLE
        elif st == SLOT_ENTRY_PENDING:
            # orderless ENTRY_PENDING — still blocks concurrent begin; may need reconcile
            reason = REASON_PENDING_RECONCILIATION
        elif st in {SLOT_OPEN, SLOT_EXIT_PENDING}:
            reason = REASON_EXISTING_SYMBOL_EXPOSURE
        else:
            reason = REASON_ACTIVE_ENTRY_LIFECYCLE
        return {"occupied": True, "reason": reason, "details": details}

    # 2) Upbit portfolio binding (OPEN / EXIT_PENDING)
    upbit_bind = session.scalar(
        select(UpbitStrategyPositionBindingEntity).where(
            UpbitStrategyPositionBindingEntity.user_broker_account_id == uba_id,
            UpbitStrategyPositionBindingEntity.symbol == sym,
            UpbitStrategyPositionBindingEntity.status.in_(
                tuple(OCCUPYING_BINDING_STATUSES)
            ),
        )
    )
    if upbit_bind is not None:
        details["upbit_binding_id"] = int(upbit_bind.binding_id)
        details["upbit_binding_status"] = str(upbit_bind.status)
        return {
            "occupied": True,
            "reason": REASON_EXISTING_SYMBOL_EXPOSURE,
            "details": details,
        }

    # 3) Strategy-owned binding (canonical AUTO exposure)
    try:
        from stock_platform.risk_engine.strategy_owned_entities import (
            BINDING_STATUS_OPEN as SOB_OPEN,
            StrategyPositionBindingEntity,
        )

        sob = session.scalar(
            select(StrategyPositionBindingEntity).where(
                StrategyPositionBindingEntity.user_broker_account_id == uba_id,
                StrategyPositionBindingEntity.symbol == sym,
                StrategyPositionBindingEntity.status == SOB_OPEN,
            )
        )
        if sob is not None:
            details["strategy_binding_id"] = int(sob.binding_id)
            details["strategy_binding_status"] = str(sob.status)
            return {
                "occupied": True,
                "reason": REASON_EXISTING_SYMBOL_EXPOSURE,
                "details": details,
            }
    except Exception:  # noqa: BLE001
        # fail-closed toward occupancy unknown → block
        return {
            "occupied": True,
            "reason": REASON_PENDING_RECONCILIATION,
            "details": {**details, "strategy_binding_error": True},
        }

    # 4) Non-terminal AUTO BUY/SELL orders for symbol
    try:
        from stock_platform.order.entities import TradingOrderEntity

        open_order = session.scalar(
            select(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id == uba_id,
                TradingOrderEntity.symbol == sym,
                TradingOrderEntity.status_code.in_(
                    tuple(_NON_TERMINAL_ORDER_STATUSES)
                ),
            )
            .limit(1)
        )
        if open_order is not None:
            details["open_order_id"] = int(open_order.order_id)
            details["open_order_side"] = str(open_order.side_code)
            details["open_order_status"] = str(open_order.status_code)
            side = str(open_order.side_code or "").upper()
            st = str(open_order.status_code or "").upper()
            if st in {"PENDING_CANCEL", "CANCEL_REQUESTED", "AMBIGUOUS", "RECONCILING"}:
                reason = REASON_PENDING_RECONCILIATION
            elif side == "SELL":
                reason = REASON_EXISTING_SYMBOL_EXPOSURE
            else:
                reason = REASON_ACTIVE_ENTRY_LIFECYCLE
            return {"occupied": True, "reason": reason, "details": details}
    except Exception:  # noqa: BLE001
        return {
            "occupied": True,
            "reason": REASON_PENDING_RECONCILIATION,
            "details": {**details, "order_scan_error": True},
        }

    return {"occupied": False, "reason": None, "details": details}


__all__ = [
    "OCCUPYING_BINDING_STATUSES",
    "OCCUPYING_SLOT_STATUSES",
    "REASON_ACTIVE_ENTRY_LIFECYCLE",
    "REASON_EXISTING_SYMBOL_EXPOSURE",
    "REASON_PENDING_RECONCILIATION",
    "inspect_symbol_auto_occupancy",
]
