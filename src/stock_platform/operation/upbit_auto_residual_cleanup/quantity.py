# -*- coding: utf-8 -*-
"""Cleanup SELL 수량 — broker attributable ∩ provenance (double-count 금지)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from stock_platform.broker.upbit.rules import round_upbit_volume
from stock_platform.operation.upbit_auto_residual_cleanup.constants import (
    KIND_HISTORICAL_ONLY,
    ZERO,
)


def _dec(value: Any) -> Decimal:
    if value is None:
        return ZERO
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return ZERO


def provenance_current_qty(truth: dict[str, Any] | None) -> Decimal:
    """현재 cleanup에 쓸 provenance qty.

    HISTORICAL_ONLY 는 항상 0 — owned/current position으로 쓰지 않음.
    """

    if not isinstance(truth, dict):
        return ZERO
    kind = str(truth.get("kind") or "").upper()
    if kind == KIND_HISTORICAL_ONLY:
        return ZERO
    for key in ("owned_qty", "current_owned_qty", "historical_remaining_qty"):
        qty = _dec(truth.get(key))
        if qty > ZERO:
            return qty
    return ZERO


def resolve_cleanup_sell_quantity(
    *,
    truth: dict[str, Any] | None,
    broker_qty: Decimal,
    same_symbol_other_current_qty: Decimal = ZERO,
) -> Decimal:
    """min(broker attributable to this residual, provenance).

    - historical-only → 0
    - same-symbol 다른 CURRENT residual 수량은 이 binding에 더하지 않음
      (호출측이 broker_qty를 이미 attributable 분량으로 넘기거나,
       same_symbol_other_current_qty로 차감)
    - broker total 전체 SELL 금지: provenance 초과분(manual) 제외
    """

    if not isinstance(truth, dict):
        return ZERO
    kind = str(truth.get("kind") or "").upper()
    if kind == KIND_HISTORICAL_ONLY:
        return ZERO

    provenance = provenance_current_qty(truth)
    if provenance <= ZERO:
        return ZERO

    broker = max(ZERO, _dec(broker_qty))
    other = max(ZERO, _dec(same_symbol_other_current_qty))
    # 동일 심볼의 다른 current residual이 broker에 포함돼 있으면 차감
    attributable_broker = max(ZERO, broker - other)
    sell_qty = min(attributable_broker, provenance)
    return round_upbit_volume(sell_qty)
