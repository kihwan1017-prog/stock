# -*- coding: utf-8 -*-
"""Cleanup 결과 lifecycle — FILLED 확인 전 residual cleared 금지."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW, round_upbit_volume
from stock_platform.operation.upbit_auto_residual_cleanup.constants import (
    KIND_CURRENT_DUST,
    KIND_CURRENT_RESIDUAL,
    STATUS_AMBIGUOUS,
    STATUS_FILLED,
    STATUS_PARTIAL_FILLED,
    ZERO,
)


def apply_verified_fill_to_residual(
    *,
    previous_residual_qty: Decimal,
    verified_executed_qty: Decimal,
    mark_price: Decimal | None,
    request_status: str,
) -> dict[str, Any]:
    """verified fill만 반영. zero-fill / ambiguous는 residual 유지."""

    prev = Decimal(str(previous_residual_qty or 0))
    filled = Decimal(str(verified_executed_qty or 0))
    status = str(request_status or "").upper()

    if status == STATUS_AMBIGUOUS:
        return {
            "residual_qty": str(prev),
            "kind_hint": None,
            "cleared": False,
            "reason": "AMBIGUOUS_NO_BLIND_RETRY",
            "additional_sell_allowed": False,
        }

    if filled <= ZERO:
        return {
            "residual_qty": str(prev),
            "kind_hint": None,
            "cleared": False,
            "reason": "ZERO_FILL_RESIDUAL_UNCHANGED",
            "additional_sell_allowed": True,
        }

    remaining = round_upbit_volume(max(ZERO, prev - filled))
    if remaining <= ZERO and status in {STATUS_FILLED, STATUS_PARTIAL_FILLED}:
        return {
            "residual_qty": "0",
            "kind_hint": "CLEARED",
            "cleared": True,
            "reason": "FULL_VERIFIED_FILL",
            "additional_sell_allowed": False,
            "cleanup_meta": {
                "state": "CLEARED",
                "requires_broker_truth": True,
            },
        }

    kind_hint = KIND_CURRENT_RESIDUAL
    if mark_price is not None and remaining > ZERO:
        notional = remaining * Decimal(str(mark_price))
        if notional < UPBIT_MIN_NOTIONAL_KRW:
            kind_hint = KIND_CURRENT_DUST

    return {
        "residual_qty": str(remaining),
        "kind_hint": kind_hint,
        "cleared": False,
        "reason": "PARTIAL_FILL_REMAINING",
        "additional_sell_allowed": kind_hint != KIND_CURRENT_DUST
        and remaining * (Decimal(str(mark_price)) if mark_price else ZERO)
        >= UPBIT_MIN_NOTIONAL_KRW,
    }
