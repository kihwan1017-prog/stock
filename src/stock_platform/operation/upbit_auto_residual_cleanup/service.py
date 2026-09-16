# -*- coding: utf-8 -*-
"""CONTROLLED_AUTO_RESIDUAL_CLEANUP — PREVIEW / PREPARE / APPLY(stub).

CLOSED binding reopen 금지 · AUTO slot 미사용 · unattended 자동 submit 금지.
실제 Upbit 주문은 broker_submit=True + injectable port + approval 모두 필요.
기본 경로(broker_submit=False)에서는 절대 주문을 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from stock_platform.operation.upbit_auto_residual_cleanup.constants import (
    ARCHITECTURE,
    CLEANUP_PATH,
    REASON_APPROVAL_REQUIRED,
    REASON_BROKER_SUBMIT_DISABLED,
    REASON_IDEMPOTENCY_BLOCK,
    REASON_QTY_EXCEEDS_ATTRIBUTABLE,
    STATUS_PREPARED,
    ZERO,
)
from stock_platform.operation.upbit_auto_residual_cleanup.eligibility import (
    EligibilityResult,
    ResidualCleanupContext,
    evaluate_eligibility,
)


class BrokerOrderPort(Protocol):
    """테스트용 mock submit — production 기본 미연결."""

    def submit_market_sell(
        self,
        *,
        uba_id: int,
        symbol: str,
        quantity: Decimal,
        idempotency_key: str,
    ) -> dict[str, Any]:
        ...


class ProductionBrokerSubmitDisabled(RuntimeError):
    """production broker 미연결."""


@dataclass
class PreparedCleanupPlan:
    status: str
    eligibility: EligibilityResult
    approval_required: bool = True
    broker_submit: bool = False
    binding_status_mutated: bool = False
    uses_auto_slot: bool = False
    enrolled_in_exit_supervisor: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "path": CLEANUP_PATH,
            "approval_required": self.approval_required,
            "broker_submit": self.broker_submit,
            "binding_status_mutated": self.binding_status_mutated,
            "uses_auto_slot": self.uses_auto_slot,
            "enrolled_in_exit_supervisor": self.enrolled_in_exit_supervisor,
            "architecture": dict(ARCHITECTURE),
            "eligibility": self.eligibility.as_dict(),
        }


def preview_cleanup(ctx: ResidualCleanupContext) -> EligibilityResult:
    """DRY-RUN eligibility — 주문/상태변경 없음."""

    result = evaluate_eligibility(ctx)
    result.broker_submit = False
    return result


def prepare_cleanup(ctx: ResidualCleanupContext) -> PreparedCleanupPlan:
    """PREPARE — PREPARED 플랜만. broker order 없음."""

    elig = preview_cleanup(ctx)
    return PreparedCleanupPlan(
        status=STATUS_PREPARED,
        eligibility=elig,
        approval_required=True,
        broker_submit=False,
        binding_status_mutated=False,
        uses_auto_slot=False,
        enrolled_in_exit_supervisor=False,
    )


def apply_cleanup(
    ctx: ResidualCleanupContext,
    *,
    approval_token: str | None,
    broker_submit: bool = False,
    order_port: BrokerOrderPort | None = None,
    prior_request_status: str | None = None,
    requested_qty: Decimal | None = None,
) -> dict[str, Any]:
    """APPLY — 명시적 approval 필수.

    broker_submit=False(기본): 주문 생성 금지, 재검증 결과만 반환.
    broker_submit=True: injectable order_port 필수 (production 기본 port 없음).
    binding status / owned_quantity / slot 변경 없음.
    """

    if not approval_token or not str(approval_token).strip():
        return {
            "ok": False,
            "reason": REASON_APPROVAL_REQUIRED,
            "broker_submit": False,
            "order_created": False,
            "architecture": dict(ARCHITECTURE),
        }

    if prior_request_status and str(prior_request_status).upper() in {
        "SUBMITTED",
        "PENDING",
        "FILLED",
        "AMBIGUOUS",
        "APPROVED",
        "PARTIAL_FILLED",
    }:
        return {
            "ok": False,
            "reason": REASON_IDEMPOTENCY_BLOCK,
            "broker_submit": False,
            "order_created": False,
            "architecture": dict(ARCHITECTURE),
        }

    # fresh revalidation
    elig = evaluate_eligibility(ctx)
    if not elig.eligible:
        return {
            "ok": False,
            "reason": elig.reason,
            "eligibility": elig.as_dict(),
            "broker_submit": False,
            "order_created": False,
            "architecture": dict(ARCHITECTURE),
        }

    qty = Decimal(str(requested_qty if requested_qty is not None else elig.eligible_qty))
    if qty > elig.eligible_qty:
        return {
            "ok": False,
            "reason": REASON_QTY_EXCEEDS_ATTRIBUTABLE,
            "eligible_qty": str(elig.eligible_qty),
            "requested_qty": str(qty),
            "broker_submit": False,
            "order_created": False,
            "architecture": dict(ARCHITECTURE),
        }

    if not broker_submit:
        return {
            "ok": True,
            "reason": REASON_BROKER_SUBMIT_DISABLED,
            "mode": "APPROVED_DRY_RUN_NO_BROKER",
            "eligibility": elig.as_dict(),
            "broker_submit": False,
            "order_created": False,
            "binding_status_mutated": False,
            "uses_auto_slot": False,
            "architecture": dict(ARCHITECTURE),
        }

    if order_port is None:
        raise ProductionBrokerSubmitDisabled(REASON_BROKER_SUBMIT_DISABLED)

    submitted = order_port.submit_market_sell(
        uba_id=ctx.uba_id,
        symbol=ctx.symbol,
        quantity=qty,
        idempotency_key=elig.idempotency_key,
    )
    return {
        "ok": True,
        "mode": "MOCK_OR_INJECTED_SUBMIT",
        "eligibility": elig.as_dict(),
        "broker_submit": True,
        "order_created": True,
        "submitted": submitted,
        "binding_status_mutated": False,
        "uses_auto_slot": False,
        "architecture": dict(ARCHITECTURE),
    }


def assert_architecture_invariants() -> dict[str, bool]:
    """테스트/증거용 — 경로가 일반 lifecycle을 우회하지 않음을 명시."""

    return {
        "closed_binding_reopened": ARCHITECTURE["closed_binding_reopened"] is False,
        "uses_auto_slot": ARCHITECTURE["uses_auto_slot"] is False,
        "uses_normal_exit_supervisor": ARCHITECTURE[
            "uses_normal_exit_supervisor"
        ]
        is False,
        "requires_explicit_approval": ARCHITECTURE["requires_explicit_approval"]
        is True,
        "unattended_auto_submit": ARCHITECTURE["unattended_auto_submit"] is False,
    }
