# -*- coding: utf-8 -*-
"""Eligibility gate — 하나라도 실패하면 cleanup order 금지."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW
from stock_platform.operation.upbit_auto_residual_cleanup.constants import (
    ALLOWED_CLEANUP_KINDS,
    BLOCKING_REQUEST_STATUSES,
    KIND_CURRENT_DUST,
    KIND_HISTORICAL_ONLY,
    MANUAL_PROTECTED_CURRENCIES,
    OWNERSHIP_CONFIDENCE_HIGH,
    REASON_ALREADY_CLEANED,
    REASON_AMBIGUOUS_ORDER,
    REASON_ACCOUNT_NOT_READY,
    REASON_BELOW_MIN_NOTIONAL,
    REASON_BROKER_MISMATCH,
    REASON_BROKER_QTY_ZERO,
    REASON_CREDENTIAL_NOT_READY,
    REASON_HISTORICAL_ONLY_BLOCKED,
    REASON_IDEMPOTENCY_BLOCK,
    REASON_KILL_SWITCH,
    REASON_MANUAL_CONTAMINATION,
    REASON_MANUAL_PROTECTED,
    REASON_NO_MARK_PRICE,
    REASON_OPEN_SELL_CONFLICT,
    REASON_OWNERSHIP_CONFIDENCE,
    REASON_PROVENANCE_QTY_ZERO,
    REASON_RECOVERY_CONFLICT,
    REASON_UBA_MISMATCH,
    REASON_UNRESOLVED_EXIT,
    REASON_UNSELLABLE_AUTO_DUST,
    ZERO,
)
from stock_platform.operation.upbit_auto_residual_cleanup.quantity import (
    provenance_current_qty,
    resolve_cleanup_sell_quantity,
)


def symbol_currency(symbol: str) -> str:
    """KRW-NEAR → NEAR."""

    s = str(symbol or "").strip().upper()
    if "-" in s:
        return s.split("-", 1)[-1]
    return s


def truth_version_hash(truth: dict[str, Any] | None) -> str:
    """idempotency용 deterministic hash."""

    payload = json.dumps(truth or {}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def build_idempotency_key(
    *,
    uba_id: int,
    binding_id: int,
    broker_code: str,
    symbol: str,
    truth: dict[str, Any] | None,
) -> str:
    raw = "|".join(
        [
            str(int(uba_id)),
            str(int(binding_id)),
            truth_version_hash(truth),
            str(broker_code or "").upper(),
            str(symbol or "").upper(),
            "CONTROLLED_AUTO_RESIDUAL_CLEANUP",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class ResidualCleanupContext:
    """게이트 평가 입력 — DB/브로커 어댑터가 채운다."""

    uba_id: int
    binding_id: int
    broker_code: str
    symbol: str
    binding_status: str
    ownership_code: str
    truth: dict[str, Any]
    broker_qty: Decimal
    mark_price: Decimal | None
    kill_switch_active: bool = False
    has_ambiguous_order: bool = False
    has_unresolved_exit: bool = False
    has_recovery_conflict: bool = False
    broker_account_ready: bool = True
    credential_ready: bool = True
    existing_open_sell_qty: Decimal = ZERO
    existing_cleanup_request_status: str | None = None
    manual_contamination: bool = False
    ownership_confidence: str = OWNERSHIP_CONFIDENCE_HIGH
    same_symbol_other_current_qty: Decimal = ZERO
    allowed_uba_ids: frozenset[int] = field(
        default_factory=lambda: frozenset({1380})
    )


@dataclass
class EligibilityResult:
    eligible: bool
    reason: str | None
    kind: str
    provenance_qty: Decimal
    broker_qty: Decimal
    eligible_qty: Decimal
    mark_price: Decimal | None
    estimated_notional: Decimal | None
    fee_estimate: Decimal | None
    minimum_notional: Decimal
    manual_contamination: bool
    existing_sell_conflict: bool
    idempotency_key: str
    broker_submit: bool = False
    expected_post_cleanup_state: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "kind": self.kind,
            "provenance_qty": str(self.provenance_qty),
            "broker_qty": str(self.broker_qty),
            "eligible_qty": str(self.eligible_qty),
            "price": None if self.mark_price is None else str(self.mark_price),
            "notional": (
                None
                if self.estimated_notional is None
                else str(self.estimated_notional)
            ),
            "fee_estimate": (
                None if self.fee_estimate is None else str(self.fee_estimate)
            ),
            "minimum_notional": str(self.minimum_notional),
            "manual_contamination": self.manual_contamination,
            "existing_sell_conflict": self.existing_sell_conflict,
            "idempotency_key": self.idempotency_key,
            "broker_submit": self.broker_submit,
            "expected_post_cleanup_state": self.expected_post_cleanup_state,
            "details": self.details,
        }


def evaluate_eligibility(ctx: ResidualCleanupContext) -> EligibilityResult:
    """공통 eligibility — 실패 시 order 금지."""

    truth = dict(ctx.truth or {})
    kind = str(truth.get("kind") or "").upper()
    provenance = provenance_current_qty(truth)
    broker_qty = Decimal(str(ctx.broker_qty or 0))
    idem = build_idempotency_key(
        uba_id=ctx.uba_id,
        binding_id=ctx.binding_id,
        broker_code=ctx.broker_code,
        symbol=ctx.symbol,
        truth=truth,
    )
    sell_conflict = Decimal(str(ctx.existing_open_sell_qty or 0)) > ZERO

    def _fail(reason: str, *, eligible_qty: Decimal = ZERO) -> EligibilityResult:
        return EligibilityResult(
            eligible=False,
            reason=reason,
            kind=kind,
            provenance_qty=provenance,
            broker_qty=broker_qty,
            eligible_qty=eligible_qty,
            mark_price=ctx.mark_price,
            estimated_notional=None,
            fee_estimate=None,
            minimum_notional=UPBIT_MIN_NOTIONAL_KRW,
            manual_contamination=bool(ctx.manual_contamination),
            existing_sell_conflict=sell_conflict,
            idempotency_key=idem,
            broker_submit=False,
            expected_post_cleanup_state={"binding_status_unchanged": True},
            details={
                "binding_id": ctx.binding_id,
                "symbol": ctx.symbol,
                "binding_status": ctx.binding_status,
            },
        )

    if int(ctx.uba_id) not in set(ctx.allowed_uba_ids):
        return _fail(REASON_UBA_MISMATCH)
    if str(ctx.broker_code or "").upper() != "UPBIT":
        return _fail(REASON_BROKER_MISMATCH)

    currency = symbol_currency(ctx.symbol)
    if currency in MANUAL_PROTECTED_CURRENCIES:
        return _fail(REASON_MANUAL_PROTECTED)
    if ctx.manual_contamination:
        return _fail(REASON_MANUAL_CONTAMINATION)

    if kind == KIND_HISTORICAL_ONLY or kind not in ALLOWED_CLEANUP_KINDS:
        return _fail(REASON_HISTORICAL_ONLY_BLOCKED)

    cleanup_meta = truth.get("cleanup") if isinstance(truth.get("cleanup"), dict) else {}
    if str(cleanup_meta.get("state") or "").upper() == "CLEARED":
        return _fail(REASON_ALREADY_CLEANED)

    req_st = str(ctx.existing_cleanup_request_status or "").upper() or None
    if req_st and req_st in BLOCKING_REQUEST_STATUSES:
        return _fail(REASON_IDEMPOTENCY_BLOCK)

    if ctx.kill_switch_active:
        return _fail(REASON_KILL_SWITCH)
    if ctx.has_ambiguous_order:
        return _fail(REASON_AMBIGUOUS_ORDER)
    if ctx.has_unresolved_exit:
        return _fail(REASON_UNRESOLVED_EXIT)
    if ctx.has_recovery_conflict:
        return _fail(REASON_RECOVERY_CONFLICT)
    if not ctx.broker_account_ready:
        return _fail(REASON_ACCOUNT_NOT_READY)
    if not ctx.credential_ready:
        return _fail(REASON_CREDENTIAL_NOT_READY)
    if str(ctx.ownership_confidence or "").upper() != OWNERSHIP_CONFIDENCE_HIGH:
        return _fail(REASON_OWNERSHIP_CONFIDENCE)

    if broker_qty <= ZERO:
        return _fail(REASON_BROKER_QTY_ZERO)
    if provenance <= ZERO:
        return _fail(REASON_PROVENANCE_QTY_ZERO)
    if sell_conflict:
        return _fail(REASON_OPEN_SELL_CONFLICT)

    eligible_qty = resolve_cleanup_sell_quantity(
        truth=truth,
        broker_qty=broker_qty,
        same_symbol_other_current_qty=ctx.same_symbol_other_current_qty,
    )
    if eligible_qty <= ZERO:
        return _fail(REASON_BROKER_QTY_ZERO, eligible_qty=ZERO)

    if ctx.mark_price is None or Decimal(str(ctx.mark_price)) <= ZERO:
        return _fail(REASON_NO_MARK_PRICE, eligible_qty=eligible_qty)

    price = Decimal(str(ctx.mark_price))
    notional = eligible_qty * price
    fee_estimate = (notional * Decimal("0.0005")).quantize(Decimal("0.01"))

    if notional < UPBIT_MIN_NOTIONAL_KRW:
        # dust vs residual below min — 동일 차단, reason만 구분
        reason = (
            REASON_UNSELLABLE_AUTO_DUST
            if kind == KIND_CURRENT_DUST
            else REASON_BELOW_MIN_NOTIONAL
        )
        return EligibilityResult(
            eligible=False,
            reason=reason,
            kind=kind,
            provenance_qty=provenance,
            broker_qty=broker_qty,
            eligible_qty=eligible_qty,
            mark_price=price,
            estimated_notional=notional,
            fee_estimate=fee_estimate,
            minimum_notional=UPBIT_MIN_NOTIONAL_KRW,
            manual_contamination=False,
            existing_sell_conflict=False,
            idempotency_key=idem,
            broker_submit=False,
            expected_post_cleanup_state={
                "binding_status_unchanged": True,
                "residual_kind_unchanged": True,
            },
            details={
                "binding_id": ctx.binding_id,
                "symbol": ctx.symbol,
                "below_min_notional": True,
            },
        )

    return EligibilityResult(
        eligible=True,
        reason=None,
        kind=kind,
        provenance_qty=provenance,
        broker_qty=broker_qty,
        eligible_qty=eligible_qty,
        mark_price=price,
        estimated_notional=notional,
        fee_estimate=fee_estimate,
        minimum_notional=UPBIT_MIN_NOTIONAL_KRW,
        manual_contamination=False,
        existing_sell_conflict=False,
        idempotency_key=idem,
        broker_submit=False,
        expected_post_cleanup_state={
            "binding_status_unchanged": True,
            "owned_quantity_unchanged": True,
            "uses_auto_slot": False,
            "after_full_fill_kind": "CLEARED_VIA_CONTROLLED_CLEANUP",
            "note": "FILLED 확인 후에만 meta cleanup provenance 기록 (이번 단계 미실행)",
        },
        details={
            "binding_id": ctx.binding_id,
            "symbol": ctx.symbol,
            "binding_status": ctx.binding_status,
            "path": "CONTROLLED_AUTO_RESIDUAL_CLEANUP",
        },
    )
