"""Ownership 판정 순수 함수 — 테스트/재사용."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stock_platform.trading.symbol_ownership.constants import (
    OWNER_AUTO,
    OWNER_AUTO_EXCLUDED,
    OWNER_FREE,
    OWNER_MANUAL,
    OWNER_UNKNOWN,
    REASON_AUTO_BINDING,
    REASON_AUTO_OPEN_ORDER,
    REASON_AUTO_SLOT,
    REASON_MANUAL_OPEN_ORDER,
    REASON_MANUAL_POSITION,
    REASON_SAME_SYMBOL_MIX,
    REASON_USER_EXCLUDED,
    SKIP_AUTO_ALREADY_MANAGED,
    SKIP_AUTO_EXCLUDED,
    SKIP_MANUAL_SYMBOL_EXCLUDED,
    SKIP_OWNERSHIP_UNKNOWN,
    SKIP_SYMBOL_HOLD,
)

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class OwnershipFacts:
    broker_position_qty: Decimal = ZERO
    auto_binding_qty: Decimal = ZERO
    auto_open_orders: int = 0
    auto_slot_active: bool = False
    manual_open_orders: int = 0
    user_excluded: bool = False
    symbol_hold_active: bool = False


@dataclass(frozen=True, slots=True)
class OwnershipDecision:
    owner: str
    reasons: tuple[str, ...]
    entry_allowed: bool
    entry_skip_reason: str | None
    manual_position_qty: Decimal
    auto_position_qty: Decimal


def decide_ownership(facts: OwnershipFacts) -> OwnershipDecision:
    """수량 분할 없이 Symbol 단위 MANUAL/AUTO/FREE/UNKNOWN."""

    auto_binding = facts.auto_binding_qty > ZERO
    auto_present = (
        auto_binding
        or facts.auto_open_orders > 0
        or facts.auto_slot_active
    )
    auto_qty = (
        facts.broker_position_qty
        if auto_present and facts.broker_position_qty > ZERO
        else (facts.auto_binding_qty if auto_present else ZERO)
    )
    manual_position_qty = (
        ZERO
        if auto_present
        else (
            facts.broker_position_qty
            if facts.broker_position_qty > ZERO
            else ZERO
        )
    )
    manual_orders = int(facts.manual_open_orders)
    manual_present = manual_position_qty > ZERO or manual_orders > 0

    reasons: list[str] = []
    if facts.user_excluded:
        reasons.append(REASON_USER_EXCLUDED)
    if facts.symbol_hold_active:
        reasons.append(SKIP_SYMBOL_HOLD)
    if auto_binding:
        reasons.append(REASON_AUTO_BINDING)
    if facts.auto_open_orders > 0:
        reasons.append(REASON_AUTO_OPEN_ORDER)
    if facts.auto_slot_active:
        reasons.append(REASON_AUTO_SLOT)
    if manual_position_qty > ZERO:
        reasons.append(REASON_MANUAL_POSITION)
    if manual_orders > 0:
        reasons.append(REASON_MANUAL_OPEN_ORDER)

    if auto_present and manual_orders > 0:
        owner = OWNER_UNKNOWN
        reasons.append(REASON_SAME_SYMBOL_MIX)
    elif auto_present:
        owner = OWNER_AUTO
    elif manual_present:
        owner = OWNER_MANUAL
    elif facts.user_excluded:
        owner = OWNER_AUTO_EXCLUDED
    else:
        owner = OWNER_FREE

    entry_allowed = False
    skip: str | None = None
    if facts.symbol_hold_active:
        skip = SKIP_SYMBOL_HOLD
    elif facts.user_excluded:
        skip = SKIP_AUTO_EXCLUDED
    elif owner == OWNER_MANUAL:
        skip = SKIP_MANUAL_SYMBOL_EXCLUDED
    elif owner == OWNER_AUTO:
        skip = SKIP_AUTO_ALREADY_MANAGED
    elif owner == OWNER_UNKNOWN:
        skip = SKIP_OWNERSHIP_UNKNOWN
    elif owner == OWNER_FREE:
        entry_allowed = True

    return OwnershipDecision(
        owner=owner,
        reasons=tuple(dict.fromkeys(reasons)),
        entry_allowed=entry_allowed,
        entry_skip_reason=skip,
        manual_position_qty=manual_position_qty,
        auto_position_qty=auto_qty,
    )
