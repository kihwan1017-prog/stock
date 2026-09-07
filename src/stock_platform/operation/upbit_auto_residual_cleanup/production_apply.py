# -*- coding: utf-8 -*-
"""Production APPLY orchestration — PREVIEW→APPROVAL→REVALIDATE→INTENT→SUBMIT→RECONCILE.

unattended/AUTO 경로에서 호출 금지. CLOSED binding status 변경 금지.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy.orm import Session

from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW
from stock_platform.operation.upbit_auto_residual_cleanup.approval import (
    ApprovalError,
    CleanupApproval,
    issue_cleanup_approval,
    validate_approval,
)
from stock_platform.operation.upbit_auto_residual_cleanup.constants import (
    ARCHITECTURE,
    CLEANUP_PATH,
    KIND_CURRENT_DUST,
    KIND_CURRENT_RESIDUAL,
    KIND_SELLABLE_CURRENT,
    REASON_APPROVAL_REQUIRED,
    STATUS_AMBIGUOUS,
    STATUS_APPROVED,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_PARTIAL_FILLED,
    STATUS_SUBMITTED,
    ZERO,
)
from stock_platform.operation.upbit_auto_residual_cleanup.eligibility import (
    ResidualCleanupContext,
    evaluate_eligibility,
)
from stock_platform.operation.upbit_auto_residual_cleanup.intent_store import (
    INTENT_META_KEY,
    intent_blocks_new_sell,
    load_intent,
    merge_cleanup_truth,
    persist_intent,
)
from stock_platform.operation.upbit_auto_residual_cleanup.lifecycle import (
    apply_verified_fill_to_residual,
)
from stock_platform.operation.upbit_auto_residual_cleanup.service import (
    BrokerOrderPort,
    preview_cleanup,
)
from stock_platform.risk_engine.strategy_owned_entities import (
    StrategyPositionBindingEntity,
)


SOURCE_OPERATOR_EXPLICIT = "OPERATOR_EXPLICIT"
SOURCE_UNATTENDED = "UNATTENDED"
SOURCE_AUTO = "AUTO"


class ProductionApplyBlocked(RuntimeError):
    """fail-closed."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def assert_operator_source(source: str) -> None:
    src = str(source or "").upper()
    if src in {SOURCE_UNATTENDED, SOURCE_AUTO, "SCHEDULER", "RUNTIME"}:
        raise ProductionApplyBlocked("UNATTENDED_CANNOT_INVOKE_PRODUCTION_SUBMIT")
    if src != SOURCE_OPERATOR_EXPLICIT:
        raise ProductionApplyBlocked("OPERATOR_EXPLICIT_SOURCE_REQUIRED")


def create_operator_approval(
    ctx: ResidualCleanupContext,
    *,
    operator_intent: str,
    ttl_seconds: int = 600,
) -> CleanupApproval:
    elig = preview_cleanup(ctx)
    return issue_cleanup_approval(
        uba_id=ctx.uba_id,
        binding_id=ctx.binding_id,
        symbol=ctx.symbol,
        truth=ctx.truth,
        elig=elig,
        operator_intent=operator_intent,
        ttl_seconds=ttl_seconds,
    )


def _load_binding(session: Session, binding_id: int, uba_id: int) -> StrategyPositionBindingEntity:
    entity = session.get(StrategyPositionBindingEntity, int(binding_id))
    if entity is None:
        raise ProductionApplyBlocked(f"binding not found: {binding_id}")
    if int(entity.user_broker_account_id) != int(uba_id):
        raise ProductionApplyBlocked("UBA_BINDING_MISMATCH")
    return entity


def execute_production_cleanup(
    session: Session,
    *,
    ctx: ResidualCleanupContext,
    approval: CleanupApproval,
    approval_secret: str,
    order_port: BrokerOrderPort,
    source: str = SOURCE_OPERATOR_EXPLICIT,
    allowed_binding_ids: frozenset[int] | None = None,
    persist_before_broker: bool = True,
    reconcile_fn: Callable[[str | None, str | None], dict[str, Any]] | None = None,
    mark_approval_consumed: Callable[[CleanupApproval], None] | None = None,
    simulate_persist_failure_after_broker: bool = False,
) -> dict[str, Any]:
    """Production submit — approval + fresh revalidation + durable intent + once submit.

    binding status / owned_quantity / AUTO slot 변경 없음.
    """

    assert_operator_source(source)

    if allowed_binding_ids is not None and int(ctx.binding_id) not in allowed_binding_ids:
        return {
            "ok": False,
            "reason": "BINDING_NOT_IN_ALLOWED_SET",
            "order_created": False,
            "architecture": dict(ARCHITECTURE),
        }

    # existing intent block
    entity = _load_binding(session, ctx.binding_id, ctx.uba_id)
    prior = load_intent(entity.meta_json if isinstance(entity.meta_json, dict) else {})
    if intent_blocks_new_sell(prior):
        return {
            "ok": False,
            "reason": "EXISTING_CLEANUP_REQUEST_BLOCK",
            "prior_status": (prior or {}).get("status"),
            "order_created": False,
            "architecture": dict(ARCHITECTURE),
        }

    # fresh eligibility
    elig = evaluate_eligibility(ctx)
    if not elig.eligible:
        return {
            "ok": False,
            "reason": elig.reason,
            "eligibility": elig.as_dict(),
            "order_created": False,
            "architecture": dict(ARCHITECTURE),
        }

    # NEAR-specific gates expected by final work (also generic)
    if str(ctx.binding_status or "").upper() != "CLOSED":
        # CLOSED만 허용 — reopen 경로 아님. 다른 status면 차단.
        return {
            "ok": False,
            "reason": "BINDING_STATUS_NOT_CLOSED_FOR_CONTROLLED_CLEANUP",
            "order_created": False,
            "architecture": dict(ARCHITECTURE),
        }
    kind = str((ctx.truth or {}).get("kind") or "").upper()
    if kind != KIND_SELLABLE_CURRENT and allowed_binding_ids:
        # final work: only sellable current may execute when allowlist set
        if kind not in {KIND_SELLABLE_CURRENT}:
            return {
                "ok": False,
                "reason": "KIND_NOT_SELLABLE_FOR_PRODUCTION_APPLY",
                "order_created": False,
                "architecture": dict(ARCHITECTURE),
            }

    try:
        validate_approval(
            approval,
            secret=approval_secret,
            uba_id=ctx.uba_id,
            binding_id=ctx.binding_id,
            symbol=ctx.symbol,
            truth=ctx.truth,
            elig=elig,
        )
    except ApprovalError as exc:
        return {
            "ok": False,
            "reason": str(exc),
            "order_created": False,
            "architecture": dict(ARCHITECTURE),
        }

    qty = Decimal(str(elig.eligible_qty))
    intent = {
        "path": CLEANUP_PATH,
        "status": STATUS_APPROVED,
        "approval_id": approval.approval_id,
        "idempotency_key": elig.idempotency_key,
        "binding_id": ctx.binding_id,
        "symbol": ctx.symbol,
        "requested_qty": str(qty),
        "source": SOURCE_OPERATOR_EXPLICIT,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    if persist_before_broker:
        persist_intent(
            session,
            binding_id=ctx.binding_id,
            uba_id=ctx.uba_id,
            intent=intent,
        )
        session.flush()

    # mark SUBMITTED before broker — durable
    intent["status"] = STATUS_SUBMITTED
    intent["submitted_at"] = _now_iso()
    if persist_before_broker:
        persist_intent(
            session,
            binding_id=ctx.binding_id,
            uba_id=ctx.uba_id,
            intent=intent,
        )
        try:
            session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            return {
                "ok": False,
                "reason": "INTENT_COMMIT_FAILED_BEFORE_BROKER",
                "error": str(exc)[:300],
                "order_created": False,
                "architecture": dict(ARCHITECTURE),
            }

    if mark_approval_consumed:
        mark_approval_consumed(approval)
    else:
        approval.consumed = True
        approval.consumed_at = _now_iso()

    submitted = order_port.submit_market_sell(
        uba_id=ctx.uba_id,
        symbol=ctx.symbol,
        quantity=qty,
        idempotency_key=elig.idempotency_key,
    )

    if simulate_persist_failure_after_broker:
        return {
            "ok": False,
            "reason": "BROKER_RESPONSE_PERSISTENCE_FAILURE",
            "final_state": STATUS_AMBIGUOUS,
            "submitted": submitted,
            "order_created": True,
            "architecture": dict(ARCHITECTURE),
        }

    if submitted.get("ambiguous"):
        intent["status"] = STATUS_AMBIGUOUS
        intent["broker_order_id"] = submitted.get("broker_order_id")
        intent["identifier"] = submitted.get("identifier")
        persist_intent(session, binding_id=ctx.binding_id, uba_id=ctx.uba_id, intent=intent)
        session.commit()
        return {
            "ok": False,
            "reason": "AMBIGUOUS_ORDER",
            "final_state": STATUS_AMBIGUOUS,
            "submitted": submitted,
            "order_created": True,
            "additional_sell_allowed": False,
            "architecture": dict(ARCHITECTURE),
        }

    if not submitted.get("accepted"):
        intent["status"] = STATUS_FAILED
        intent["reject_code"] = submitted.get("reject_code")
        persist_intent(session, binding_id=ctx.binding_id, uba_id=ctx.uba_id, intent=intent)
        session.commit()
        return {
            "ok": False,
            "reason": submitted.get("reject_code") or STATUS_FAILED,
            "final_state": STATUS_FAILED,
            "submitted": submitted,
            "order_created": False,
            "architecture": dict(ARCHITECTURE),
        }

    broker_uuid = submitted.get("broker_order_id")
    identifier = submitted.get("identifier")
    intent["broker_order_id"] = broker_uuid
    intent["identifier"] = identifier
    persist_intent(session, binding_id=ctx.binding_id, uba_id=ctx.uba_id, intent=intent)
    session.commit()

    remote: dict[str, Any] = {}
    if reconcile_fn is not None:
        remote = reconcile_fn(broker_uuid, identifier) or {}
    elif hasattr(order_port, "get_order"):
        try:
            remote = order_port.get_order(  # type: ignore[attr-defined]
                uba_id=ctx.uba_id, uuid=broker_uuid, identifier=identifier
            )
        except Exception as exc:  # noqa: BLE001
            remote = {"reconcile_error": str(exc)[:300]}

    final = classify_remote_fill(
        previous_residual_qty=qty,
        remote=remote,
        mark_price=elig.mark_price,
    )

    cleanup_block = {
        "cleanup_status": final["final_state"],
        "approval_id": approval.approval_id,
        "idempotency_key": elig.idempotency_key,
        "requested_qty": str(qty),
        "executed_qty": final["executed_qty"],
        "broker_order_uuid": broker_uuid,
        "identifier": identifier,
        "submitted_at": submitted.get("submitted_at"),
        "confirmed_at": _now_iso(),
        "final_remaining_qty": final["remaining_qty"],
        "broker_truth_source": "UPBIT_GET_ORDER",
        "remote_state": remote.get("state"),
        "economic_audit": {
            "note": "cleanup PnL not written into historical binding realized_pnl",
            "paid_fee": remote.get("paid_fee"),
            "executed_volume": remote.get("executed_volume"),
        },
    }

    kind_update = final.get("kind_hint")
    qty_update = final["remaining_qty"]
    if final["final_state"] == STATUS_FILLED and Decimal(str(final["remaining_qty"])) <= ZERO:
        cleanup_block["state"] = "CLEARED"
        kind_update = "CLEARED_VIA_CONTROLLED_CLEANUP"
        qty_update = "0"

    # FILLED/PARTIAL만 truth.cleanup 갱신 — zero/failed는 residual qty 유지
    if final["final_state"] in {STATUS_FILLED, STATUS_PARTIAL_FILLED}:
        merge_cleanup_truth(
            session,
            binding_id=ctx.binding_id,
            uba_id=ctx.uba_id,
            cleanup_block=cleanup_block,
            residual_kind_update=kind_update
            if final["final_state"] == STATUS_PARTIAL_FILLED
            else kind_update,
            residual_qty_update=qty_update
            if final["final_state"] in {STATUS_FILLED, STATUS_PARTIAL_FILLED}
            else None,
        )
        # CLOSED status 유지 — owned_quantity 런타임 필드도 변경하지 않음
        session.commit()
    else:
        intent["status"] = final["final_state"]
        intent["reconcile"] = {
            "executed_qty": final["executed_qty"],
            "remaining_qty": final["remaining_qty"],
        }
        persist_intent(session, binding_id=ctx.binding_id, uba_id=ctx.uba_id, intent=intent)
        session.commit()

    return {
        "ok": final["final_state"] in {STATUS_FILLED, STATUS_PARTIAL_FILLED, "PENDING"},
        "final_state": final["final_state"],
        "requested_qty": str(qty),
        "executed_qty": final["executed_qty"],
        "remaining_qty": final["remaining_qty"],
        "broker_uuid": broker_uuid,
        "identifier": identifier,
        "submitted": submitted,
        "remote": {
            "state": remote.get("state"),
            "executed_volume": remote.get("executed_volume"),
            "remaining_volume": remote.get("remaining_volume"),
            "paid_fee": remote.get("paid_fee"),
        },
        "order_created": True,
        "binding_status_mutated": False,
        "owned_quantity_mutated": False,
        "architecture": dict(ARCHITECTURE),
        "eligibility": elig.as_dict(),
        "minimum_notional": str(UPBIT_MIN_NOTIONAL_KRW),
    }


def classify_remote_fill(
    *,
    previous_residual_qty: Decimal,
    remote: dict[str, Any],
    mark_price: Decimal | None,
) -> dict[str, Any]:
    """Upbit get_order truth → FILLED/PARTIAL/PENDING/AMBIGUOUS/ZERO."""

    if remote.get("reconcile_error"):
        return {
            "final_state": STATUS_AMBIGUOUS,
            "executed_qty": "0",
            "remaining_qty": str(previous_residual_qty),
            "kind_hint": None,
        }

    state = str(remote.get("state") or "").lower()
    executed = Decimal(str(remote.get("executed_volume") or 0))
    remaining_vol = Decimal(str(remote.get("remaining_volume") or 0))

    if state in {"", "unknown"} and "uuid" not in remote and "identifier" not in remote:
        # empty remote — treat pending if we have uuid elsewhere handled by caller
        pass

    life = apply_verified_fill_to_residual(
        previous_residual_qty=previous_residual_qty,
        verified_executed_qty=executed,
        mark_price=mark_price,
        request_status=(
            STATUS_AMBIGUOUS
            if state in {"ambiguous"}
            else STATUS_FILLED
            if state == "done" and remaining_vol <= ZERO
            else STATUS_PARTIAL_FILLED
            if executed > ZERO
            else "PENDING"
        ),
    )

    if state in {"wait", "watch", "pending"} and executed <= ZERO:
        return {
            "final_state": "PENDING",
            "executed_qty": "0",
            "remaining_qty": str(previous_residual_qty),
            "kind_hint": None,
        }
    if state == "cancel" and executed <= ZERO:
        return {
            "final_state": STATUS_FAILED,
            "executed_qty": "0",
            "remaining_qty": str(previous_residual_qty),
            "kind_hint": None,
        }
    if life.get("reason") == "AMBIGUOUS_NO_BLIND_RETRY":
        return {
            "final_state": STATUS_AMBIGUOUS,
            "executed_qty": str(executed),
            "remaining_qty": str(previous_residual_qty),
            "kind_hint": None,
        }
    if executed <= ZERO:
        return {
            "final_state": "ZERO_FILL",
            "executed_qty": "0",
            "remaining_qty": str(previous_residual_qty),
            "kind_hint": None,
        }
    if life.get("cleared"):
        return {
            "final_state": STATUS_FILLED,
            "executed_qty": str(executed),
            "remaining_qty": "0",
            "kind_hint": "CLEARED_VIA_CONTROLLED_CLEANUP",
        }
    hint = life.get("kind_hint") or KIND_CURRENT_RESIDUAL
    if hint == KIND_CURRENT_DUST:
        pass
    return {
        "final_state": STATUS_PARTIAL_FILLED,
        "executed_qty": str(executed),
        "remaining_qty": life["residual_qty"],
        "kind_hint": hint,
    }
